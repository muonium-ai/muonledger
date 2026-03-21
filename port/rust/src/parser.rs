//! Textual journal parser for Ledger-format files.
//!
//! Ported from ledger's `textual.cc` via the Python reference implementation.
//! The [`TextualParser`] reads plain-text journal files (or strings) and
//! populates a [`Journal`] with [`Transaction`] and [`Post`] objects.
//!
//! The parser handles the core Ledger grammar:
//!
//!   - Transaction header lines: `DATE [=AUX_DATE] [STATE] [(CODE)] PAYEE [; NOTE]`
//!   - Posting lines: `  [STATE] ACCOUNT  AMOUNT [@ COST] [; NOTE]`
//!   - Comments: lines starting with `;`, `#`, `%`, `|`, or `*`
//!   - Metadata in comments: `; key: value` and `; :tag1:tag2:`
//!   - Directives: `account`, `commodity`, `include`, `comment`/`end comment`,
//!     `P` (price), `D` (default commodity), `Y`/`year` (default year)

use std::fmt;
use std::path::Path;

use chrono::NaiveDate;
use regex::Regex;

use lazy_static::lazy_static;

use crate::amount::Amount;
use crate::auto_xact::AutomatedTransaction;
use crate::item::{ItemState, Position};
use crate::journal::Journal;
use crate::periodic_xact::PeriodicTransaction;
use crate::post::{Post, POST_COST_IN_FULL, POST_MUST_BALANCE, POST_VIRTUAL};

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// Raised when the parser encounters invalid journal syntax.
#[derive(Debug, Clone)]
pub struct ParseError {
    pub message: String,
    pub line_num: usize,
    pub source: String,
}

impl ParseError {
    pub fn new(message: &str, line_num: usize, source: &str) -> Self {
        Self {
            message: message.to_string(),
            line_num,
            source: source.to_string(),
        }
    }
}

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if !self.source.is_empty() {
            write!(f, "{}:{}: {}", self.source, self.line_num, self.message)
        } else {
            write!(f, "line {}: {}", self.line_num, self.message)
        }
    }
}

impl std::error::Error for ParseError {}

// ---------------------------------------------------------------------------
// Date parsing
// ---------------------------------------------------------------------------

lazy_static! {
    static ref DATE_RE: Regex =
        Regex::new(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})").unwrap();
    static ref TAG_LINE_RE: Regex = Regex::new(r"^:(.+):$").unwrap();
    static ref META_RE: Regex = Regex::new(r"^(\S+?):\s*(.*)$").unwrap();
}

fn parse_date(text: &str) -> Result<(NaiveDate, usize), String> {
    let caps = DATE_RE.captures(text.trim_start())
        .ok_or_else(|| format!("Cannot parse date: {:?}", text))?;
    let y: i32 = caps[1].parse().map_err(|e| format!("{}", e))?;
    let m: u32 = caps[2].parse().map_err(|e| format!("{}", e))?;
    let d: u32 = caps[3].parse().map_err(|e| format!("{}", e))?;
    let date = NaiveDate::from_ymd_opt(y, m, d)
        .ok_or_else(|| format!("Invalid date: {}-{}-{}", y, m, d))?;
    let match_end = caps.get(0).unwrap().end();
    Ok((date, match_end))
}

// ---------------------------------------------------------------------------
// Cost splitting helper
// ---------------------------------------------------------------------------

/// Split an amount+cost string at `@` or `@@`.
///
/// Returns (amount_text, cost_text_or_None, is_total_cost).
fn split_amount_and_cost(text: &str) -> (&str, Option<&str>, bool) {
    let bytes = text.as_bytes();
    let mut in_quote = false;
    let mut i = 0;
    while i < bytes.len() {
        let ch = bytes[i];
        if ch == b'"' {
            in_quote = !in_quote;
        } else if !in_quote && ch == b'@' {
            if i + 1 < bytes.len() && bytes[i + 1] == b'@' {
                let amt = text[..i].trim_end();
                let cost = text[i + 2..].trim_start();
                return (amt, Some(cost), true);
            } else {
                let amt = text[..i].trim_end();
                let cost = text[i + 1..].trim_start();
                return (amt, Some(cost), false);
            }
        }
        i += 1;
    }
    (text, None, false)
}

// ---------------------------------------------------------------------------
// Tag parsing in comments
// ---------------------------------------------------------------------------

/// Parse metadata from a comment string.
///
/// Returns (clean_note_or_None, tags as key/value pairs).
/// Tags like `:tag1:tag2:` produce `{tag1: "", tag2: ""}`.
/// Key-value pairs like `key: value` produce `{key: value}`.
fn parse_comment_metadata(comment: &str) -> (Option<String>, Vec<(String, String)>) {
    let text = comment.trim();
    if text.is_empty() {
        return (None, Vec::new());
    }

    // Check for tag line: :tag1:tag2:
    if let Some(caps) = TAG_LINE_RE.captures(text) {
        let tags_str = &caps[1];
        let mut metadata = Vec::new();
        for tag in tags_str.split(':') {
            let tag = tag.trim();
            if !tag.is_empty() {
                metadata.push((tag.to_string(), String::new()));
            }
        }
        return (None, metadata);
    }

    // Check for key: value metadata
    if let Some(caps) = META_RE.captures(text) {
        let key = caps[1].to_string();
        let value = caps[2].trim().to_string();
        return (None, vec![(key, value)]);
    }

    // Plain note text
    (Some(text.to_string()), Vec::new())
}

// ---------------------------------------------------------------------------
// TextualParser
// ---------------------------------------------------------------------------

/// Parse Ledger-format textual journal files.
pub struct TextualParser;

impl TextualParser {
    pub fn new() -> Self {
        Self
    }

    /// Parse journal data from a string.
    ///
    /// Returns the number of transactions parsed.
    pub fn parse_string(
        &self,
        text: &str,
        journal: &mut Journal,
    ) -> Result<usize, ParseError> {
        self.parse_text(text, journal, "<string>")
    }

    /// Parse a journal file and populate the journal.
    ///
    /// Returns the number of transactions parsed.
    pub fn parse_file(
        &self,
        path: &Path,
        journal: &mut Journal,
    ) -> Result<usize, ParseError> {
        let text = std::fs::read_to_string(path).map_err(|e| {
            ParseError::new(&format!("Cannot read file: {}", e), 0, &path.display().to_string())
        })?;
        journal.sources.push(path.display().to_string());
        self.parse_text(&text, journal, &path.display().to_string())
    }

    // ------------------------------------------------------------------
    // Internal implementation
    // ------------------------------------------------------------------

    fn parse_text(
        &self,
        text: &str,
        journal: &mut Journal,
        source_name: &str,
    ) -> Result<usize, ParseError> {
        let lines: Vec<&str> = text.split('\n').collect();
        let mut count = 0;
        let mut i = 0;

        while i < lines.len() {
            let line = lines[i].trim_end_matches('\r');

            // Empty line - skip
            if line.is_empty() || line.chars().all(|c| c.is_whitespace()) {
                i += 1;
                continue;
            }

            let first_char = line.chars().next().unwrap();

            // Comment lines
            if ";#%|*".contains(first_char) {
                i += 1;
                continue;
            }

            // Multi-line comment block: comment ... end comment
            if line.trim() == "comment" || line.starts_with("comment ") {
                i += 1;
                while i < lines.len() {
                    let cline = lines[i].trim_end_matches('\r');
                    if cline.trim() == "end comment" {
                        i += 1;
                        break;
                    }
                    i += 1;
                }
                continue;
            }

            // Test blocks: skip "test ..." through "end test"
            if line.starts_with("test ") || line.trim() == "test" {
                i += 1;
                while i < lines.len() {
                    let tline = lines[i].trim_end_matches('\r');
                    if tline.trim() == "end test" {
                        i += 1;
                        break;
                    }
                    i += 1;
                }
                continue;
            }

            // apply account / end apply account
            if line.starts_with("apply account ") {
                let prefix = line["apply account ".len()..].trim().to_string();
                if !prefix.is_empty() {
                    journal.apply_account_stack.push(prefix);
                }
                i += 1;
                continue;
            }
            if line.trim() == "end apply account" {
                journal.apply_account_stack.pop();
                i += 1;
                continue;
            }

            // apply tag / end apply tag
            if line.starts_with("apply tag ") {
                let tag = line["apply tag ".len()..].trim().to_string();
                if !tag.is_empty() {
                    journal.apply_tag_stack.push(tag);
                }
                i += 1;
                continue;
            }
            if line.trim() == "end apply tag" {
                journal.apply_tag_stack.pop();
                i += 1;
                continue;
            }

            // end (standalone) - block comment termination or generic end
            if line.starts_with("end ") || line.trim() == "end" {
                i += 1;
                continue;
            }

            // Directives starting with ! or @ (alternative prefixes, skip)
            if first_char == '!' || first_char == '@' {
                i += 1;
                continue;
            }

            // account directive
            if line.starts_with("account ") {
                i = self.account_directive(&lines, i, journal);
                continue;
            }

            // commodity directive
            if line.starts_with("commodity ") {
                i = self.commodity_directive(&lines, i, journal);
                continue;
            }

            // include directive
            if line.starts_with("include ") {
                i = self.include_directive(&lines, i, journal, source_name)?;
                continue;
            }

            // alias directive (top-level)
            if line.starts_with("alias ") {
                self.alias_directive(line, journal);
                i += 1;
                continue;
            }

            // bucket directive
            if line.starts_with("bucket ") {
                self.bucket_directive(line, journal);
                i += 1;
                continue;
            }

            // tag directive
            if line.starts_with("tag ") {
                self.tag_directive(&lines, i, journal);
                i += 1;
                while i < lines.len() {
                    let sline = lines[i].trim_end_matches('\r');
                    if sline.is_empty() || (!sline.starts_with(' ') && !sline.starts_with('\t')) {
                        break;
                    }
                    i += 1;
                }
                continue;
            }

            // payee directive
            if line.starts_with("payee ") {
                self.payee_directive(&lines, i, journal);
                i += 1;
                while i < lines.len() {
                    let sline = lines[i].trim_end_matches('\r');
                    if sline.is_empty() || (!sline.starts_with(' ') && !sline.starts_with('\t')) {
                        break;
                    }
                    i += 1;
                }
                continue;
            }

            // define directive
            if line.starts_with("define ") {
                self.define_directive(line, journal);
                i += 1;
                continue;
            }

            // P price directive
            if first_char == 'P' && line.len() > 1 && line.as_bytes()[1] == b' ' {
                self.price_directive(line, journal, i + 1, source_name)?;
                i += 1;
                continue;
            }

            // D default commodity directive
            if first_char == 'D' && line.len() > 1 && line.as_bytes()[1] == b' ' {
                self.default_commodity_directive(line, journal);
                i += 1;
                continue;
            }

            // N no-market commodity directive
            if first_char == 'N' && line.len() > 1 && line.as_bytes()[1] == b' ' {
                self.no_market_directive(line, journal);
                i += 1;
                continue;
            }

            // A default account (bucket) directive
            if first_char == 'A' && line.len() > 1 && line.as_bytes()[1] == b' ' {
                self.bucket_directive_short(line, journal);
                i += 1;
                continue;
            }

            // Y / year directive
            if first_char == 'Y' && line.len() > 1 && line.as_bytes()[1] == b' ' {
                self.year_directive(line, journal);
                i += 1;
                continue;
            }
            if line.starts_with("year ") {
                self.year_directive(line, journal);
                i += 1;
                continue;
            }

            // Skip other single-char directives: C, etc.
            if "Ccnac".contains(first_char) && line.len() > 1 && line.as_bytes()[1] == b' ' {
                i += 1;
                continue;
            }

            // Automated transactions (= PREDICATE)
            if first_char == '=' {
                let (auto_xact, end_i) =
                    self.parse_auto_xact(&lines, i, journal, source_name)?;
                if let Some(ax) = auto_xact {
                    journal.auto_xacts.push(ax);
                }
                i = end_i;
                continue;
            }

            // Periodic transactions (~ PERIOD)
            if first_char == '~' {
                let (periodic_xact, end_i) =
                    self.parse_periodic_xact(&lines, i, journal, source_name)?;
                if let Some(px) = periodic_xact {
                    journal.periodic_xacts.push(px);
                }
                i = end_i;
                continue;
            }

            // Transaction: starts with a digit (date)
            if first_char.is_ascii_digit() {
                let (xact, end_i) = self.parse_xact(&lines, i, journal, source_name)?;
                if let Some(xact) = xact {
                    match journal.add_xact(xact) {
                        Ok(true) => count += 1,
                        Ok(false) => {}
                        Err(e) => {
                            return Err(ParseError::new(
                                &format!("Transaction does not balance: {}", e),
                                i + 1,
                                source_name,
                            ));
                        }
                    }
                }
                i = end_i;
                continue;
            }

            // Indented line outside a transaction context - skip
            if first_char == ' ' || first_char == '\t' {
                i += 1;
                continue;
            }

            // Unknown line - skip
            i += 1;
        }

        // Apply automated transactions to all parsed postings
        if !journal.auto_xacts.is_empty() {
            self.apply_auto_xacts(journal);
        }

        journal.was_loaded = true;
        Ok(count)
    }

    /// Apply all automated transactions to existing postings.
    ///
    /// For each posting in each transaction, check all automated transaction
    /// predicates. If a match is found, generate the template postings and
    /// add them to the transaction.
    fn apply_auto_xacts(&self, journal: &mut Journal) {
        // Collect all generated postings indexed by transaction
        let mut additions: Vec<(usize, Vec<Post>)> = Vec::new();

        for (xact_idx, xact) in journal.xacts.iter().enumerate() {
            let mut new_posts = Vec::new();
            for post in &xact.posts {
                for auto_xact in &journal.auto_xacts {
                    if auto_xact.matches(post, journal) {
                        let generated = auto_xact.apply_to(post);
                        new_posts.extend(generated);
                    }
                }
            }
            if !new_posts.is_empty() {
                additions.push((xact_idx, new_posts));
            }
        }

        // Apply additions
        for (xact_idx, posts) in additions {
            for post in posts {
                journal.xacts[xact_idx].add_post(post);
            }
        }
    }

    // ------------------------------------------------------------------
    // Directive handlers
    // ------------------------------------------------------------------

    fn consume_sub_directives<'a>(
        &self,
        lines: &[&'a str],
        start: usize,
    ) -> (Vec<(String, String)>, usize) {
        let mut sub_directives = Vec::new();
        let mut i = start;
        while i < lines.len() {
            let sline = lines[i].trim_end_matches('\r');
            if sline.is_empty() || (!sline.starts_with(' ') && !sline.starts_with('\t')) {
                break;
            }
            let stripped = sline.trim_start();
            if stripped.is_empty() || stripped.starts_with(';') {
                i += 1;
                continue;
            }
            let mut parts = stripped.splitn(2, char::is_whitespace);
            let keyword = parts.next().unwrap_or("").to_string();
            let argument = parts.next().unwrap_or("").to_string();
            sub_directives.push((keyword, argument));
            i += 1;
        }
        (sub_directives, i)
    }

    fn account_directive(
        &self,
        lines: &[&str],
        start: usize,
        journal: &mut Journal,
    ) -> usize {
        let line = lines[start].trim_end_matches('\r');
        let account_name = line["account ".len()..].trim().to_string();
        let _account_id = journal.find_account(&account_name, true);

        let (sub_directives, next_i) = self.consume_sub_directives(lines, start + 1);

        for (keyword, argument) in &sub_directives {
            if keyword == "note" {
                if let Some(id) = journal.find_account(&account_name, false) {
                    journal.accounts.get_mut(id).note = Some(argument.clone());
                }
            } else if keyword == "default" {
                if let Some(id) = journal.find_account(&account_name, false) {
                    journal.bucket = Some(id);
                }
            } else if keyword == "alias" {
                let alias_name = argument.trim().to_string();
                if !alias_name.is_empty() {
                    if let Some(id) = journal.find_account(&account_name, false) {
                        journal.account_aliases.insert(alias_name, id);
                    }
                }
            }
        }

        next_i
    }

    fn commodity_directive(
        &self,
        lines: &[&str],
        start: usize,
        journal: &mut Journal,
    ) -> usize {
        let line = lines[start].trim_end_matches('\r');
        let symbol = line["commodity ".len()..].trim();
        let _commodity_id = journal.commodity_pool.find_or_create(symbol);

        let (_sub_directives, next_i) = self.consume_sub_directives(lines, start + 1);
        next_i
    }

    fn include_directive(
        &self,
        lines: &[&str],
        start: usize,
        journal: &mut Journal,
        source_name: &str,
    ) -> Result<usize, ParseError> {
        let line = lines[start].trim_end_matches('\r');
        let mut include_path = line["include ".len()..].trim();

        // Strip surrounding quotes
        if include_path.len() >= 2 {
            let first = include_path.chars().next().unwrap();
            let last = include_path.chars().last().unwrap();
            if (first == '"' || first == '\'') && last == first {
                include_path = &include_path[1..include_path.len() - 1];
            }
        }

        // Resolve relative to current file's directory
        let resolved = if !source_name.is_empty() && source_name != "<string>" {
            let parent = Path::new(source_name).parent().unwrap_or(Path::new("."));
            parent.join(include_path)
        } else {
            Path::new(include_path).to_path_buf()
        };

        if !resolved.exists() {
            return Err(ParseError::new(
                &format!("File to include was not found: {}", resolved.display()),
                start + 1,
                source_name,
            ));
        }

        self.parse_file(&resolved, journal)?;
        Ok(start + 1)
    }

    fn year_directive(&self, line: &str, journal: &mut Journal) {
        let rest = if line.starts_with("year ") {
            line["year ".len()..].trim()
        } else {
            line[1..].trim()
        };
        if let Ok(year) = rest.parse::<i32>() {
            journal.default_year = Some(year);
        }
    }

    /// Parse a top-level `alias` directive: `alias ALIAS=ACCOUNT`
    fn alias_directive(&self, line: &str, journal: &mut Journal) {
        let rest = line["alias ".len()..].trim();
        if let Some(eq_pos) = rest.find('=') {
            let alias_name = rest[..eq_pos].trim().to_string();
            let account_name = rest[eq_pos + 1..].trim();
            if !alias_name.is_empty() && !account_name.is_empty() {
                let account_id = journal.find_account(account_name, true).unwrap();
                journal.account_aliases.insert(alias_name, account_id);
            }
        }
    }

    /// Parse a `bucket` directive: `bucket ACCOUNT`
    fn bucket_directive(&self, line: &str, journal: &mut Journal) {
        let account_name = line["bucket ".len()..].trim();
        if !account_name.is_empty() {
            let account_id = journal.find_account(account_name, true).unwrap();
            journal.bucket = Some(account_id);
        }
    }

    /// Parse an `A` directive (short form of bucket): `A ACCOUNT`
    fn bucket_directive_short(&self, line: &str, journal: &mut Journal) {
        let account_name = line[1..].trim();
        if !account_name.is_empty() {
            let account_id = journal.find_account(account_name, true).unwrap();
            journal.bucket = Some(account_id);
        }
    }

    /// Parse a `tag` directive: `tag TAGNAME`
    fn tag_directive(&self, lines: &[&str], start: usize, journal: &mut Journal) {
        let line = lines[start].trim_end_matches('\r');
        let tag_name = line["tag ".len()..].trim().to_string();
        if !tag_name.is_empty() {
            journal.tag_declarations.push(tag_name);
        }
    }

    /// Parse a `payee` directive: `payee PAYEENAME`
    fn payee_directive(&self, lines: &[&str], start: usize, journal: &mut Journal) {
        let line = lines[start].trim_end_matches('\r');
        let payee_name = line["payee ".len()..].trim().to_string();
        if !payee_name.is_empty() {
            journal.payee_declarations.push(payee_name);
        }
    }

    /// Parse a `define` directive: `define VAR=EXPR`
    fn define_directive(&self, line: &str, journal: &mut Journal) {
        let rest = line["define ".len()..].trim();
        if let Some(eq_pos) = rest.find('=') {
            let var_name = rest[..eq_pos].trim().to_string();
            let expr = rest[eq_pos + 1..].trim().to_string();
            if !var_name.is_empty() {
                journal.defines.insert(var_name, expr);
            }
        }
    }

    /// Parse a `P` price directive: `P DATE COMMODITY PRICE`
    fn price_directive(
        &self,
        line: &str,
        journal: &mut Journal,
        line_num: usize,
        source_name: &str,
    ) -> Result<(), ParseError> {
        let rest = line[1..].trim_start();
        let (price_date, date_end) = parse_date(rest).map_err(|e| {
            ParseError::new(
                &format!("Expected date in P directive: {}", e),
                line_num,
                source_name,
            )
        })?;
        let rest = rest[date_end..].trim_start();
        let mut parts = rest.splitn(2, char::is_whitespace);
        let commodity_symbol = parts.next().unwrap_or("").to_string();
        let price_text = parts.next().unwrap_or("").trim();
        if commodity_symbol.is_empty() || price_text.is_empty() {
            return Err(ParseError::new(
                "Expected commodity and price in P directive",
                line_num,
                source_name,
            ));
        }
        let price_amount = Amount::parse(price_text).map_err(|e| {
            ParseError::new(
                &format!("Invalid price amount: {}", e),
                line_num,
                source_name,
            )
        })?;
        journal
            .prices
            .push((price_date, commodity_symbol, price_amount));
        Ok(())
    }

    /// Parse a `D` default commodity directive: `D AMOUNT`
    fn default_commodity_directive(&self, line: &str, journal: &mut Journal) {
        let rest = line[1..].trim_start();
        if !rest.is_empty() {
            if let Ok(amt) = Amount::parse(rest) {
                if let Some(sym) = amt.commodity() {
                    let commodity_id = journal.commodity_pool.find_or_create(sym);
                    let commodity = journal.commodity_pool.get_mut(commodity_id);
                    commodity.precision = amt.precision();
                    journal.commodity_pool.default_commodity = Some(commodity_id);
                }
            }
        }
    }

    /// Parse an `N` no-market commodity directive: `N COMMODITY`
    fn no_market_directive(&self, line: &str, journal: &mut Journal) {
        let symbol = line[1..].trim();
        if !symbol.is_empty() {
            journal.no_market_commodities.push(symbol.to_string());
            let commodity_id = journal.commodity_pool.find_or_create(symbol);
            let commodity = journal.commodity_pool.get_mut(commodity_id);
            commodity.add_flags(crate::commodity::CommodityStyle::NOMARKET);
        }
    }

    // ------------------------------------------------------------------
    // Automated / Periodic transaction parsing
    // ------------------------------------------------------------------

    /// Parse an automated transaction (`= PREDICATE` followed by indented postings).
    fn parse_auto_xact(
        &self,
        lines: &[&str],
        start: usize,
        journal: &mut Journal,
        source_name: &str,
    ) -> Result<(Option<AutomatedTransaction>, usize), ParseError> {
        let line = lines[start].trim_end_matches('\r');
        // Skip the '=' character and extract the predicate
        let predicate = line[1..].trim().to_string();
        if predicate.is_empty() {
            // Empty predicate — skip the block
            let mut i = start + 1;
            while i < lines.len() {
                let pline = lines[i].trim_end_matches('\r');
                if pline.is_empty() {
                    break;
                }
                let fc = pline.chars().next().unwrap();
                if fc != ' ' && fc != '\t' && fc != ';' {
                    break;
                }
                i += 1;
            }
            return Ok((None, i));
        }

        let mut auto_xact = AutomatedTransaction::new(&predicate);
        let mut i = start + 1;

        while i < lines.len() {
            let pline = lines[i].trim_end_matches('\r');

            // Blank line or non-indented line ends the block
            if pline.is_empty() {
                break;
            }
            let fc = pline.chars().next().unwrap();
            if fc != ' ' && fc != '\t' && fc != ';' {
                break;
            }

            let pline_stripped = pline.trim_start();

            // Skip comment lines within the auto xact block
            if pline_stripped.starts_with(';') {
                i += 1;
                continue;
            }

            // Parse as posting (reuse the same parse_post logic)
            if let Some(post) = self.parse_post(pline, i + 1, journal, source_name)? {
                auto_xact.add_post(post);
            }

            i += 1;
        }

        Ok((Some(auto_xact), i))
    }

    /// Parse a periodic transaction (`~ PERIOD` followed by indented postings).
    fn parse_periodic_xact(
        &self,
        lines: &[&str],
        start: usize,
        journal: &mut Journal,
        source_name: &str,
    ) -> Result<(Option<PeriodicTransaction>, usize), ParseError> {
        let line = lines[start].trim_end_matches('\r');
        // Skip the '~' character and extract the period expression
        let period_expr = line[1..].trim().to_string();
        if period_expr.is_empty() {
            // Empty period — skip the block
            let mut i = start + 1;
            while i < lines.len() {
                let pline = lines[i].trim_end_matches('\r');
                if pline.is_empty() {
                    break;
                }
                let fc = pline.chars().next().unwrap();
                if fc != ' ' && fc != '\t' && fc != ';' {
                    break;
                }
                i += 1;
            }
            return Ok((None, i));
        }

        let mut periodic_xact = PeriodicTransaction::new(&period_expr);
        let mut i = start + 1;

        while i < lines.len() {
            let pline = lines[i].trim_end_matches('\r');

            // Blank line or non-indented line ends the block
            if pline.is_empty() {
                break;
            }
            let fc = pline.chars().next().unwrap();
            if fc != ' ' && fc != '\t' && fc != ';' {
                break;
            }

            let pline_stripped = pline.trim_start();

            // Skip comment lines within the periodic xact block
            if pline_stripped.starts_with(';') {
                i += 1;
                continue;
            }

            // Parse as posting (reuse the same parse_post logic)
            if let Some(post) = self.parse_post(pline, i + 1, journal, source_name)? {
                periodic_xact.add_post(post);
            }

            i += 1;
        }

        Ok((Some(periodic_xact), i))
    }

    // ------------------------------------------------------------------
    // Transaction parsing
    // ------------------------------------------------------------------

    fn parse_xact(
        &self,
        lines: &[&str],
        start: usize,
        journal: &mut Journal,
        source_name: &str,
    ) -> Result<(Option<crate::xact::Transaction>, usize), ParseError> {
        let line = lines[start].trim_end_matches('\r');
        let line_num = start + 1;

        let mut rest = line;

        // 1. Parse date(s): DATE[=AUX_DATE]
        let (primary_date, date_end) = parse_date(rest).map_err(|e| {
            ParseError::new(&format!("Expected date: {}", e), line_num, source_name)
        })?;
        rest = &rest[date_end..];

        let mut aux_date: Option<NaiveDate> = None;
        if rest.starts_with('=') {
            rest = &rest[1..];
            let (ad, ae) = parse_date(rest).map_err(|e| {
                ParseError::new(
                    &format!("Expected auxiliary date after '=': {}", e),
                    line_num,
                    source_name,
                )
            })?;
            aux_date = Some(ad);
            rest = &rest[ae..];
        }

        rest = rest.trim_start();

        // 2. Parse optional state marker
        let mut state = ItemState::Uncleared;
        if rest.starts_with('*') {
            state = ItemState::Cleared;
            rest = rest[1..].trim_start();
        } else if rest.starts_with('!') {
            state = ItemState::Pending;
            rest = rest[1..].trim_start();
        }

        // 3. Parse optional code: (CODE)
        let mut code: Option<String> = None;
        if rest.starts_with('(') {
            if let Some(close) = rest.find(')') {
                code = Some(rest[1..close].to_string());
                rest = rest[close + 1..].trim_start();
            }
        }

        // 4. Parse payee and optional inline note
        let mut xact_note: Option<String> = None;
        let mut xact_metadata: Vec<(String, String)> = Vec::new();
        let payee;

        if let Some(semi_pos) = rest.find(';') {
            payee = rest[..semi_pos].trim_end().to_string();
            let comment_text = rest[semi_pos + 1..].trim();
            let (note_text, meta) = parse_comment_metadata(comment_text);
            xact_note = note_text.or_else(|| {
                if !comment_text.is_empty() {
                    Some(comment_text.to_string())
                } else {
                    None
                }
            });
            xact_metadata = meta;
        } else {
            payee = rest.trim_end().to_string();
        }

        // Build the transaction
        let mut xact = crate::xact::Transaction::with_payee(&payee);
        xact.item.date = Some(primary_date);
        xact.item.date_aux = aux_date;
        xact.item.state = state;
        xact.code = code;
        xact.item.note = xact_note;
        xact.item.position = Some(Position {
            pathname: source_name.to_string(),
            beg_line: line_num,
            ..Position::default()
        });
        for (k, v) in &xact_metadata {
            xact.item.set_tag(k, v);
        }
        // Apply tags from apply tag stack
        for tag in &journal.apply_tag_stack {
            xact.item.set_tag(tag, "");
        }

        // -- Parse posting lines --
        let mut i = start + 1;
        while i < lines.len() {
            let pline = lines[i].trim_end_matches('\r');

            // Blank line or non-indented line ends the transaction
            if pline.is_empty() {
                break;
            }
            let fc = pline.chars().next().unwrap();
            if fc != ' ' && fc != '\t' {
                break;
            }

            let pline_stripped = pline.trim_start();

            // Comment line attached to the transaction or previous posting
            if pline_stripped.starts_with(';') {
                let comment_text = pline_stripped[1..].trim();
                let (note_text, meta) = parse_comment_metadata(comment_text);

                // Apply metadata to the last posting if one exists,
                // otherwise to the transaction
                if !xact.posts.is_empty() {
                    let target = xact.posts.last_mut().unwrap();
                    for (k, v) in &meta {
                        target.item.set_tag(k, v);
                    }
                    if let Some(nt) = note_text {
                        if let Some(existing) = &target.item.note {
                            target.item.note = Some(format!("{}\n{}", existing, nt));
                        } else {
                            target.item.note = Some(nt);
                        }
                    }
                } else {
                    for (k, v) in &meta {
                        xact.item.set_tag(k, v);
                    }
                    if let Some(nt) = note_text {
                        if let Some(existing) = &xact.item.note {
                            xact.item.note = Some(format!("{}\n{}", existing, nt));
                        } else {
                            xact.item.note = Some(nt);
                        }
                    }
                }

                i += 1;
                continue;
            }

            // Parse as posting
            if let Some(post) = self.parse_post(pline, i + 1, journal, source_name)? {
                xact.add_post(post);
            }

            i += 1;
        }

        // Set end line
        if let Some(pos) = &mut xact.item.position {
            pos.end_line = i;
        }

        Ok((Some(xact), i))
    }

    fn parse_post(
        &self,
        line: &str,
        line_num: usize,
        journal: &mut Journal,
        source_name: &str,
    ) -> Result<Option<Post>, ParseError> {
        let rest_initial = line.trim_start();
        if rest_initial.is_empty() {
            return Ok(None);
        }

        let mut rest = rest_initial;

        // 1. Optional state marker on the posting itself
        let mut post_state = ItemState::Uncleared;
        if rest.starts_with('*') {
            post_state = ItemState::Cleared;
            rest = rest[1..].trim_start();
        } else if rest.starts_with('!') {
            post_state = ItemState::Pending;
            rest = rest[1..].trim_start();
        }

        // 2. Detect virtual account brackets
        let mut is_virtual = false;
        let mut must_balance = true;
        let account_name: String;

        if rest.starts_with('(') {
            // Virtual posting (does not need to balance)
            is_virtual = true;
            must_balance = false;
            let close = rest.find(')').ok_or_else(|| {
                ParseError::new("Expected ')' for virtual account", line_num, source_name)
            })?;
            account_name = rest[1..close].trim().to_string();
            rest = &rest[close + 1..];
        } else if rest.starts_with('[') {
            // Balanced virtual posting (must balance)
            is_virtual = true;
            must_balance = true;
            let close = rest.find(']').ok_or_else(|| {
                ParseError::new(
                    "Expected ']' for balanced virtual account",
                    line_num,
                    source_name,
                )
            })?;
            account_name = rest[1..close].trim().to_string();
            rest = &rest[close + 1..];
        } else {
            // Real account
            let (acct, remainder) = split_account_and_rest(rest);
            account_name = acct.to_string();
            rest = remainder;
        }

        // Resolve aliases and apply-account prefix
        let resolved_name = if let Some(&alias_id) = journal.account_aliases.get(&account_name) {
            journal.account_fullname(alias_id)
        } else if !journal.apply_account_stack.is_empty() {
            let prefix = journal.apply_account_stack.join(":");
            format!("{}:{}", prefix, account_name)
        } else {
            account_name.clone()
        };

        // Look up or create the account in the journal
        let account_id = journal.find_account(&resolved_name, true).unwrap();

        // 3. Parse inline comment
        let rest = rest.trim_start();
        let mut post_note: Option<String> = None;
        let mut post_metadata: Vec<(String, String)> = Vec::new();

        // Separate amount portion from inline comment
        let amount_text;
        if !rest.is_empty() {
            let semi_pos = find_comment_start(rest);
            if let Some(sp) = semi_pos {
                amount_text = rest[..sp].trim_end();
                let comment_text = rest[sp + 1..].trim();
                let (note_text, meta) = parse_comment_metadata(comment_text);
                post_note = note_text.or_else(|| {
                    if !comment_text.is_empty() {
                        Some(comment_text.to_string())
                    } else {
                        None
                    }
                });
                post_metadata = meta;
            } else {
                amount_text = rest.trim_end();
            }
        } else {
            amount_text = "";
        }

        // 4. Parse amount and optional cost
        let mut amount: Option<Amount> = None;
        let mut cost: Option<Amount> = None;
        let mut post_flags: u32 = 0;

        if is_virtual {
            post_flags |= POST_VIRTUAL;
            if must_balance {
                post_flags |= POST_MUST_BALANCE;
            }
        }

        if !amount_text.is_empty() {
            let (amt_part, cost_part, cost_is_total) = split_amount_and_cost(amount_text);

            if !amt_part.is_empty() {
                amount = Some(Amount::parse(amt_part).map_err(|e| {
                    ParseError::new(
                        &format!("Invalid amount: {}", e),
                        line_num,
                        source_name,
                    )
                })?);
            }

            if let Some(cost_text) = cost_part {
                let cost_amount = Amount::parse(cost_text).map_err(|e| {
                    ParseError::new(
                        &format!("Invalid cost amount: {}", e),
                        line_num,
                        source_name,
                    )
                })?;

                if cost_is_total {
                    post_flags |= POST_COST_IN_FULL;
                    cost = Some(cost_amount);
                } else {
                    // Per-unit cost: total cost = |amount| * cost_per_unit
                    if let Some(ref amt) = amount {
                        if !amt.is_null() {
                            let abs_amt = amt.abs().number(); // strip commodity
                            let total_cost = &abs_amt * &cost_amount;
                            cost = Some(total_cost);
                        } else {
                            cost = Some(cost_amount);
                        }
                    } else {
                        cost = Some(cost_amount);
                    }
                }
            }
        }

        // Build the Post
        let mut post = if let Some(amt) = amount {
            Post::with_account_and_amount(account_id, amt)
        } else {
            Post::with_account(account_id)
        };
        post.item.state = post_state;
        post.cost = cost;
        post.item.position = Some(Position {
            pathname: source_name.to_string(),
            beg_line: line_num,
            ..Position::default()
        });
        if post_flags != 0 {
            post.item.add_flags(post_flags);
        }
        if let Some(note) = post_note {
            post.item.note = Some(note);
        }
        for (k, v) in &post_metadata {
            post.item.set_tag(k, v);
        }

        Ok(Some(post))
    }
}

impl Default for TextualParser {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

/// Split a posting line into account name and the remainder.
///
/// Account names end at:
/// - Two consecutive spaces
/// - A tab character
/// - A semicolon (inline comment)
/// - End of line
fn split_account_and_rest(text: &str) -> (&str, &str) {
    let bytes = text.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        let ch = bytes[i];
        // Tab separates account from amount
        if ch == b'\t' {
            return (text[..i].trim_end(), &text[i + 1..]);
        }
        // Two consecutive spaces
        if ch == b' ' && i + 1 < bytes.len() && bytes[i + 1] == b' ' {
            return (text[..i].trim_end(), &text[i + 2..]);
        }
        // Semicolon starts a comment
        if ch == b';' {
            return (text[..i].trim_end(), &text[i..]);
        }
        i += 1;
    }
    // Entire line is the account name (no amount)
    (text.trim_end(), "")
}

/// Find the position of an inline comment `;` in amount text.
///
/// Returns None if no comment found. Respects quoted strings.
fn find_comment_start(text: &str) -> Option<usize> {
    let mut in_quote = false;
    for (i, ch) in text.char_indices() {
        if ch == '"' {
            in_quote = !in_quote;
        } else if !in_quote && ch == ';' {
            return Some(i);
        }
    }
    None
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::item::ItemState;
    #[allow(unused_imports)]
    use crate::post::{POST_COST_IN_FULL, POST_MUST_BALANCE, POST_VIRTUAL};
    use chrono::NaiveDate;

    fn parse(text: &str) -> Journal {
        let mut journal = Journal::new();
        let parser = TextualParser::new();
        parser.parse_string(text, &mut journal).unwrap();
        journal
    }

    // -----------------------------------------------------------------------
    // Basic transaction parsing
    // -----------------------------------------------------------------------

    #[test]
    fn test_two_postings() {
        let text = "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1);
        let xact = &journal.xacts[0];
        assert_eq!(xact.payee, "Grocery Store");
        assert_eq!(xact.item.date, Some(NaiveDate::from_ymd_opt(2024, 1, 15).unwrap()));
        assert_eq!(xact.posts.len(), 2);
        let acct0 = journal.account_fullname(xact.posts[0].account_id.unwrap());
        assert_eq!(acct0, "Expenses:Food");
        let amt0 = xact.posts[0].amount.as_ref().unwrap();
        assert_eq!(amt0.commodity(), Some("$"));
        // Second posting auto-balanced
        let acct1 = journal.account_fullname(xact.posts[1].account_id.unwrap());
        assert_eq!(acct1, "Assets:Checking");
        assert!(xact.posts[1].amount.is_some());
        assert!(xact.posts[1].amount.as_ref().unwrap().is_negative());
    }

    #[test]
    fn test_parse_string_returns_count() {
        let text = "\
2024/01/15 Grocery Store
    Expenses:Food       $42.50
    Assets:Checking
";
        let mut journal = Journal::new();
        let parser = TextualParser::new();
        let count = parser.parse_string(text, &mut journal).unwrap();
        assert_eq!(count, 1);
    }

    // -----------------------------------------------------------------------
    // Multiple transactions
    // -----------------------------------------------------------------------

    #[test]
    fn test_three_transactions() {
        let text = "\
2024/01/01 Opening Balance
    Assets:Checking     $1,000.00
    Equity:Opening

2024/01/05 Coffee Shop
    Expenses:Dining     $4.50
    Assets:Checking

2024/01/10 Salary
    Assets:Checking     $3000.00
    Income:Salary
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 3);
        assert_eq!(journal.xacts[0].payee, "Opening Balance");
        assert_eq!(journal.xacts[1].payee, "Coffee Shop");
        assert_eq!(journal.xacts[2].payee, "Salary");
    }

    #[test]
    fn test_transactions_without_blank_lines() {
        let text = "\
2024/01/01 First
    Expenses:A     $10.00
    Assets:B
2024/01/02 Second
    Expenses:C     $20.00
    Assets:D
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 2);
    }

    // -----------------------------------------------------------------------
    // Date parsing
    // -----------------------------------------------------------------------

    #[test]
    fn test_slash_date() {
        let text = "\
2024/03/15 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(
            journal.xacts[0].item.date,
            Some(NaiveDate::from_ymd_opt(2024, 3, 15).unwrap())
        );
    }

    #[test]
    fn test_dash_date() {
        let text = "\
2024-03-15 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(
            journal.xacts[0].item.date,
            Some(NaiveDate::from_ymd_opt(2024, 3, 15).unwrap())
        );
    }

    #[test]
    fn test_aux_date() {
        let text = "\
2024/03/15=2024/03/10 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        let xact = &journal.xacts[0];
        assert_eq!(xact.item.date, Some(NaiveDate::from_ymd_opt(2024, 3, 15).unwrap()));
        assert_eq!(
            xact.item.date_aux,
            Some(NaiveDate::from_ymd_opt(2024, 3, 10).unwrap())
        );
    }

    #[test]
    fn test_aux_date_dash() {
        let text = "\
2024-03-15=2024-03-10 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        let xact = &journal.xacts[0];
        assert_eq!(xact.item.date, Some(NaiveDate::from_ymd_opt(2024, 3, 15).unwrap()));
        assert_eq!(
            xact.item.date_aux,
            Some(NaiveDate::from_ymd_opt(2024, 3, 10).unwrap())
        );
    }

    // -----------------------------------------------------------------------
    // State markers
    // -----------------------------------------------------------------------

    #[test]
    fn test_cleared() {
        let text = "\
2024/01/01 * Cleared Transaction
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.xacts[0].item.state, ItemState::Cleared);
    }

    #[test]
    fn test_pending() {
        let text = "\
2024/01/01 ! Pending Transaction
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.xacts[0].item.state, ItemState::Pending);
    }

    #[test]
    fn test_uncleared() {
        let text = "\
2024/01/01 Uncleared Transaction
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.xacts[0].item.state, ItemState::Uncleared);
    }

    #[test]
    fn test_posting_state() {
        let text = "\
2024/01/01 Test
    * Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.xacts[0].posts[0].item.state, ItemState::Cleared);
    }

    // -----------------------------------------------------------------------
    // Code parsing
    // -----------------------------------------------------------------------

    #[test]
    fn test_code() {
        let text = "\
2024/01/01 (1042) Grocery Store
    Expenses:Food     $10.00
    Assets:Checking
";
        let journal = parse(text);
        assert_eq!(journal.xacts[0].code, Some("1042".to_string()));
    }

    #[test]
    fn test_code_with_state() {
        let text = "\
2024/01/01 * (CHK#100) Payee
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        let xact = &journal.xacts[0];
        assert_eq!(xact.item.state, ItemState::Cleared);
        assert_eq!(xact.code, Some("CHK#100".to_string()));
        assert_eq!(xact.payee, "Payee");
    }

    #[test]
    fn test_no_code() {
        let text = "\
2024/01/01 Payee
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert!(journal.xacts[0].code.is_none());
    }

    // -----------------------------------------------------------------------
    // Amount formats
    // -----------------------------------------------------------------------

    #[test]
    fn test_prefix_commodity() {
        let text = "\
2024/01/01 Test
    Expenses:A     $100.00
    Assets:B
";
        let journal = parse(text);
        let amt = journal.xacts[0].posts[0].amount.as_ref().unwrap();
        assert_eq!(amt.commodity(), Some("$"));
        assert!((amt.to_double().unwrap() - 100.0).abs() < 0.001);
    }

    #[test]
    fn test_suffix_commodity() {
        let text = "\
2024/01/01 Test
    Expenses:A     100.00 EUR
    Assets:B
";
        let journal = parse(text);
        let amt = journal.xacts[0].posts[0].amount.as_ref().unwrap();
        assert_eq!(amt.commodity(), Some("EUR"));
        assert!((amt.to_double().unwrap() - 100.0).abs() < 0.001);
    }

    #[test]
    fn test_negative_amount() {
        let text = "\
2024/01/01 Test
    Expenses:A     $100.00
    Assets:B       -$100.00
";
        let journal = parse(text);
        let amt = journal.xacts[0].posts[1].amount.as_ref().unwrap();
        assert!((amt.to_double().unwrap() - (-100.0)).abs() < 0.001);
    }

    // -----------------------------------------------------------------------
    // Auto-balance
    // -----------------------------------------------------------------------

    #[test]
    fn test_single_null_posting() {
        let text = "\
2024/01/01 Test
    Expenses:Food     $42.50
    Assets:Checking
";
        let journal = parse(text);
        let xact = &journal.xacts[0];
        assert_eq!(xact.posts.len(), 2);
        let balanced_post = &xact.posts[1];
        assert!(balanced_post.amount.is_some());
        assert!((balanced_post.amount.as_ref().unwrap().to_double().unwrap() - (-42.50)).abs() < 0.001);
    }

    #[test]
    fn test_multiple_postings_one_null() {
        let text = "\
2024/01/01 Test
    Expenses:Food     $20.00
    Expenses:Drink    $10.00
    Assets:Checking
";
        let journal = parse(text);
        let xact = &journal.xacts[0];
        assert_eq!(xact.posts.len(), 3);
        assert!((xact.posts[2].amount.as_ref().unwrap().to_double().unwrap() - (-30.00)).abs() < 0.001);
    }

    // -----------------------------------------------------------------------
    // Virtual accounts
    // -----------------------------------------------------------------------

    #[test]
    fn test_virtual_parenthesized() {
        let text = "\
2024/01/01 Test
    Expenses:Food     $10.00
    Assets:Checking   -$10.00
    (Budget:Food)     $-10.00
";
        let journal = parse(text);
        let xact = &journal.xacts[0];
        assert_eq!(xact.posts.len(), 3);
        let vpost = &xact.posts[2];
        assert!(vpost.is_virtual());
        assert!(!vpost.must_balance());
        let acct = journal.account_fullname(vpost.account_id.unwrap());
        assert_eq!(acct, "Budget:Food");
    }

    #[test]
    fn test_virtual_bracketed() {
        let text = "\
2024/01/01 Test
    Expenses:Food     $10.00
    Assets:Checking   -$10.00
    [Budget:Food]     $0.00
";
        let journal = parse(text);
        let xact = &journal.xacts[0];
        let vpost = &xact.posts[2];
        assert!(vpost.is_virtual());
        assert!(vpost.must_balance());
        let acct = journal.account_fullname(vpost.account_id.unwrap());
        assert_eq!(acct, "Budget:Food");
    }

    // -----------------------------------------------------------------------
    // Cost (@ and @@)
    // -----------------------------------------------------------------------

    #[test]
    fn test_per_unit_cost() {
        let text = "\
2024/01/01 Investment
    Assets:Brokerage     50 AAPL @ $30.00
    Assets:Checking
";
        let journal = parse(text);
        let xact = &journal.xacts[0];
        let post = &xact.posts[0];
        assert!((post.amount.as_ref().unwrap().to_double().unwrap() - 50.0).abs() < 0.001);
        assert_eq!(post.amount.as_ref().unwrap().commodity(), Some("AAPL"));
        // Cost should be total = 50 * $30 = $1500
        assert!(post.cost.is_some());
        assert!((post.cost.as_ref().unwrap().to_double().unwrap() - 1500.0).abs() < 0.01);
        assert_eq!(post.cost.as_ref().unwrap().commodity(), Some("$"));
    }

    #[test]
    fn test_total_cost() {
        let text = "\
2024/01/01 Investment
    Assets:Brokerage     50 AAPL @@ $1500.00
    Assets:Checking
";
        let journal = parse(text);
        let xact = &journal.xacts[0];
        let post = &xact.posts[0];
        assert!((post.amount.as_ref().unwrap().to_double().unwrap() - 50.0).abs() < 0.001);
        assert_eq!(post.amount.as_ref().unwrap().commodity(), Some("AAPL"));
        assert!(post.cost.is_some());
        assert!((post.cost.as_ref().unwrap().to_double().unwrap() - 1500.0).abs() < 0.01);
        assert!(post.item.has_flags(POST_COST_IN_FULL));
    }

    // -----------------------------------------------------------------------
    // Comments and metadata
    // -----------------------------------------------------------------------

    #[test]
    fn test_comment_lines_skipped() {
        let text = "\
; This is a comment
# Another comment
2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn test_inline_xact_note() {
        let text = "\
2024/01/01 Test ; transaction note
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert!(journal.xacts[0].item.note.is_some());
        assert!(journal.xacts[0].item.note.as_ref().unwrap().contains("transaction note"));
    }

    #[test]
    fn test_posting_inline_comment() {
        let text = "\
2024/01/01 Test
    Expenses:A     $10.00 ; posting note
    Assets:B
";
        let journal = parse(text);
        let post = &journal.xacts[0].posts[0];
        assert!(post.item.note.is_some());
        assert!(post.item.note.as_ref().unwrap().contains("posting note"));
    }

    #[test]
    fn test_metadata_key_value() {
        let text = "\
2024/01/01 Test
    ; Sample: Value
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        let xact = &journal.xacts[0];
        assert_eq!(xact.item.get_tag("Sample"), Some("Value"));
    }

    #[test]
    fn test_metadata_tags() {
        let text = "\
2024/01/01 Test
    Expenses:A     $10.00
    ; :MyTag:AnotherTag:
    Assets:B
";
        let journal = parse(text);
        let post = &journal.xacts[0].posts[0];
        assert!(post.item.has_tag("MyTag"));
        assert!(post.item.has_tag("AnotherTag"));
    }

    #[test]
    fn test_posting_metadata() {
        let text = "\
2024/01/01 Test
    Expenses:A     $10.00
    ; Sample: Another Value
    Assets:B
";
        let journal = parse(text);
        let post = &journal.xacts[0].posts[0];
        assert_eq!(post.item.get_tag("Sample"), Some("Another Value"));
    }

    // -----------------------------------------------------------------------
    // Edge cases
    // -----------------------------------------------------------------------

    #[test]
    fn test_empty_string() {
        let journal = parse("");
        assert_eq!(journal.xacts.len(), 0);
    }

    #[test]
    fn test_only_comments() {
        let journal = parse("; comment\n# another\n");
        assert_eq!(journal.xacts.len(), 0);
    }

    #[test]
    fn test_account_with_spaces() {
        let text = "\
2024/01/01 Test
    Expenses:Food and Drink  $10.00
    Assets:Bank Account
";
        let journal = parse(text);
        let acct = journal.account_fullname(journal.xacts[0].posts[0].account_id.unwrap());
        assert_eq!(acct, "Expenses:Food and Drink");
    }

    #[test]
    fn test_tab_separated() {
        let text = "2024/01/01 Test\n\tExpenses:Food\t$10.00\n\tAssets:Cash\n";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1);
        let acct = journal.account_fullname(journal.xacts[0].posts[0].account_id.unwrap());
        assert_eq!(acct, "Expenses:Food");
    }

    #[test]
    fn test_thousands_separator() {
        let text = "\
2024/01/01 Test
    Assets:Checking     $1,000.00
    Equity:Opening
";
        let journal = parse(text);
        let amt = journal.xacts[0].posts[0].amount.as_ref().unwrap();
        assert!((amt.to_double().unwrap() - 1000.0).abs() < 0.01);
    }

    #[test]
    fn test_was_loaded_flag() {
        let journal = parse("2024/01/01 T\n    E:A  $1\n    A:B\n");
        assert!(journal.was_loaded);
    }

    #[test]
    fn test_parse_automated_transactions() {
        let text = "\
= /^Expenses:Books/
    (Liabilities:Taxes)  -0.10

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1);
        assert_eq!(journal.auto_xacts.len(), 1);
        assert_eq!(journal.auto_xacts[0].predicate_expr, "/^Expenses:Books/");
        assert_eq!(journal.auto_xacts[0].posts.len(), 1);
    }

    #[test]
    fn test_parse_periodic_transactions() {
        let text = "\
~ Monthly
    Assets:Bank:Checking  $500.00
    Income:Salary

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1);
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert_eq!(journal.periodic_xacts[0].period_expr, "Monthly");
        assert_eq!(journal.periodic_xacts[0].posts.len(), 2);
    }

    #[test]
    fn test_auto_xact_applied_to_matching_posts() {
        let text = "\
= /Expenses:Books/
    (Liabilities:Taxes)  -0.10

2024/01/01 Test
    Expenses:Books     $20.00
    Assets:Checking
";
        let journal = parse(text);
        assert_eq!(journal.auto_xacts.len(), 1);
        // The transaction should have the original 2 posts + 1 generated
        assert_eq!(journal.xacts[0].posts.len(), 3);
        // The generated post should be flagged
        let gen_post = &journal.xacts[0].posts[2];
        assert!(gen_post.item.has_flags(crate::post::POST_GENERATED));
        // $20.00 * -0.10 = $-2.00
        let amt = gen_post.amount.as_ref().unwrap();
        assert!((amt.to_double().unwrap() - (-2.0)).abs() < 0.01);
    }

    #[test]
    fn test_auto_xact_not_applied_to_nonmatching() {
        let text = "\
= /Expenses:Books/
    (Liabilities:Taxes)  -0.10

2024/01/01 Test
    Expenses:Food     $20.00
    Assets:Checking
";
        let journal = parse(text);
        // No match, so only 2 original posts
        assert_eq!(journal.xacts[0].posts.len(), 2);
    }

    #[test]
    fn test_auto_xact_with_fixed_amount() {
        let text = "\
= /Expenses/
    (Liabilities:Taxes)  $5.00

2024/01/01 Test
    Expenses:Books     $20.00
    Assets:Checking
";
        let journal = parse(text);
        // Should have 3 posts (2 original + 1 generated with fixed $5.00)
        assert_eq!(journal.xacts[0].posts.len(), 3);
        let gen_post = &journal.xacts[0].posts[2];
        let amt = gen_post.amount.as_ref().unwrap();
        assert!((amt.to_double().unwrap() - 5.0).abs() < 0.01);
    }

    #[test]
    fn test_multiple_auto_xacts() {
        let text = "\
= /Expenses/
    (Liabilities:Tax1)  -0.05

= /Books/
    (Liabilities:Tax2)  -0.02

2024/01/01 Test
    Expenses:Books     $100.00
    Assets:Checking
";
        let journal = parse(text);
        assert_eq!(journal.auto_xacts.len(), 2);
        // Both match Expenses:Books: 2 original + 2 generated
        assert_eq!(journal.xacts[0].posts.len(), 4);
    }

    #[test]
    fn test_periodic_xact_with_comments() {
        let text = "\
~ Weekly
    ; This is a budget comment
    Expenses:Food  $100.00
    Assets:Checking

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.periodic_xacts.len(), 1);
        assert_eq!(journal.periodic_xacts[0].posts.len(), 2);
    }

    #[test]
    fn test_auto_xact_empty_predicate_skipped() {
        let text = "\
=
    (Liabilities:Taxes)  -0.10

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.auto_xacts.len(), 0);
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn test_periodic_xact_empty_period_skipped() {
        let text = "\
~
    Expenses:Food  $100.00

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.periodic_xacts.len(), 0);
        assert_eq!(journal.xacts.len(), 1);
    }

    // -----------------------------------------------------------------------
    // Realistic multi-transaction journal
    // -----------------------------------------------------------------------

    const REALISTIC_JOURNAL: &str = "\
; Sample ledger file

2024/05/01 * Opening Balance
    Assets:Bank:Checking                           $1,000.00
    Equity:Opening Balances

2024/05/03=2024/05/01 * Investment purchase
    Assets:Brokerage                                 50 AAPL @ $30.00
    Equity:Opening Balances

2024/05/14 * Payday
    Assets:Bank:Checking                             $500.00
    Income:Salary

2024/05/27 (100) Credit card company
    ; This is an xact note!
    ; Sample: Value
    Liabilities:MasterCard                            $20.00
    ; This is a posting note!
    ; Sample: Another Value
    ; :MyTag:
    Assets:Bank:Checking
    ; :AnotherTag:
";

    #[test]
    fn test_parse_all_transactions() {
        let journal = parse(REALISTIC_JOURNAL);
        assert_eq!(journal.xacts.len(), 4);
    }

    #[test]
    fn test_first_transaction() {
        let journal = parse(REALISTIC_JOURNAL);
        let xact = &journal.xacts[0];
        assert_eq!(xact.item.date, Some(NaiveDate::from_ymd_opt(2024, 5, 1).unwrap()));
        assert_eq!(xact.item.state, ItemState::Cleared);
        assert_eq!(xact.payee, "Opening Balance");
        assert_eq!(xact.posts.len(), 2);
    }

    #[test]
    fn test_investment_transaction() {
        let journal = parse(REALISTIC_JOURNAL);
        let xact = &journal.xacts[1];
        assert_eq!(xact.item.date, Some(NaiveDate::from_ymd_opt(2024, 5, 3).unwrap()));
        assert_eq!(
            xact.item.date_aux,
            Some(NaiveDate::from_ymd_opt(2024, 5, 1).unwrap())
        );
        let post = &xact.posts[0];
        let acct = journal.account_fullname(post.account_id.unwrap());
        assert_eq!(acct, "Assets:Brokerage");
        assert_eq!(post.amount.as_ref().unwrap().commodity(), Some("AAPL"));
        assert!(post.cost.is_some());
    }

    #[test]
    fn test_code_transaction() {
        let journal = parse(REALISTIC_JOURNAL);
        let xact = &journal.xacts[3];
        assert_eq!(xact.code, Some("100".to_string()));
        assert_eq!(xact.payee, "Credit card company");
    }

    #[test]
    fn test_metadata_on_transaction() {
        let journal = parse(REALISTIC_JOURNAL);
        let xact = &journal.xacts[3];
        assert_eq!(xact.item.get_tag("Sample"), Some("Value"));
    }

    #[test]
    fn test_metadata_on_posting() {
        let journal = parse(REALISTIC_JOURNAL);
        let xact = &journal.xacts[3];
        let post0 = &xact.posts[0];
        assert_eq!(post0.item.get_tag("Sample"), Some("Another Value"));
        assert!(post0.item.has_tag("MyTag"));
    }

    #[test]
    fn test_second_posting_tag() {
        let journal = parse(REALISTIC_JOURNAL);
        let xact = &journal.xacts[3];
        let post1 = &xact.posts[1];
        assert!(post1.item.has_tag("AnotherTag"));
    }

    #[test]
    fn test_account_tree() {
        let mut journal = parse(REALISTIC_JOURNAL);
        let checking = journal.accounts.find_account(
            journal.accounts.root_id(),
            "Assets:Bank:Checking",
            false,
        );
        assert!(checking.is_some());
    }

    #[test]
    fn test_all_balances() {
        let journal = parse(REALISTIC_JOURNAL);
        assert!(journal.xacts.iter().all(|x| x.posts.len() >= 2));
    }

    // -----------------------------------------------------------------------
    // Directives
    // -----------------------------------------------------------------------

    #[test]
    fn test_account_directive() {
        let text = "\
account Assets:Checking
    note Main checking account

2024/01/01 Test
    Assets:Checking     $10.00
    Expenses:A
";
        let mut journal = parse(text);
        assert_eq!(journal.xacts.len(), 1);
        let acct_id = journal.accounts.find_account(
            journal.accounts.root_id(),
            "Assets:Checking",
            false,
        );
        assert!(acct_id.is_some());
        let acct = journal.accounts.get(acct_id.unwrap());
        assert_eq!(acct.note, Some("Main checking account".to_string()));
    }

    #[test]
    fn test_commodity_directive() {
        let text = "\
commodity $
    format $1,000.00

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1);
        assert!(journal.commodity_pool.contains("$"));
    }

    #[test]
    fn test_year_directive() {
        let text = "\
Y 2024

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.default_year, Some(2024));
    }

    #[test]
    fn test_year_directive_word() {
        let text = "\
year 2025

2025/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.default_year, Some(2025));
    }

    // -----------------------------------------------------------------------
    // Error cases
    // -----------------------------------------------------------------------

    #[test]
    fn test_unbalanced_transaction() {
        let text = "\
2024/01/01 Test
    Expenses:A     $42.50
    Assets:B       -$10.00
";
        let mut journal = Journal::new();
        let parser = TextualParser::new();
        let result = parser.parse_string(text, &mut journal);
        assert!(result.is_err());
    }

    // -----------------------------------------------------------------------
    // Comment block
    // -----------------------------------------------------------------------

    #[test]
    fn test_comment_block() {
        let text = "\
comment
This is a block comment
that spans multiple lines
end comment

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1);
    }

    // -----------------------------------------------------------------------
    // Split helpers
    // -----------------------------------------------------------------------

    #[test]
    fn test_split_account_two_spaces() {
        let (acct, rest) = split_account_and_rest("Expenses:Food and Drink  $10.00");
        assert_eq!(acct, "Expenses:Food and Drink");
        assert_eq!(rest, "$10.00");
    }

    #[test]
    fn test_split_account_tab() {
        let (acct, rest) = split_account_and_rest("Expenses:Food\t$10.00");
        assert_eq!(acct, "Expenses:Food");
        assert_eq!(rest, "$10.00");
    }

    #[test]
    fn test_split_account_no_amount() {
        let (acct, rest) = split_account_and_rest("Assets:Checking");
        assert_eq!(acct, "Assets:Checking");
        assert_eq!(rest, "");
    }

    #[test]
    fn test_split_amount_and_cost_per_unit() {
        let (amt, cost, total) = split_amount_and_cost("50 AAPL @ $30.00");
        assert_eq!(amt, "50 AAPL");
        assert_eq!(cost, Some("$30.00"));
        assert!(!total);
    }

    #[test]
    fn test_split_amount_and_cost_total() {
        let (amt, cost, total) = split_amount_and_cost("50 AAPL @@ $1500.00");
        assert_eq!(amt, "50 AAPL");
        assert_eq!(cost, Some("$1500.00"));
        assert!(total);
    }

    #[test]
    fn test_split_amount_no_cost() {
        let (amt, cost, total) = split_amount_and_cost("$42.50");
        assert_eq!(amt, "$42.50");
        assert!(cost.is_none());
        assert!(!total);
    }

    // -----------------------------------------------------------------------
    // find_account on AccountArena is &mut self, but this test verifies
    // that account_tree test above works by checking the parser populated
    // the arena correctly.
    // -----------------------------------------------------------------------

    #[test]
    fn test_account_tree_via_fullname() {
        let journal = parse(REALISTIC_JOURNAL);
        // The parser created these accounts; verify through the arena
        let mut found_checking = false;
        let all_ids = journal.accounts.flatten(journal.accounts.root_id());
        for id in all_ids {
            if journal.accounts.fullname(id) == "Assets:Bank:Checking" {
                found_checking = true;
            }
        }
        assert!(found_checking);
    }

    // -----------------------------------------------------------------------
    // Alias directive
    // -----------------------------------------------------------------------

    #[test]
    fn test_alias_directive_top_level() {
        let text = "\
alias chk=Assets:Checking

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert!(journal.account_aliases.contains_key("chk"));
        let acct_id = journal.account_aliases["chk"];
        assert_eq!(journal.account_fullname(acct_id), "Assets:Checking");
    }

    #[test]
    fn test_alias_directive_with_spaces() {
        let text = "\
alias savings = Assets:Bank:Savings

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert!(journal.account_aliases.contains_key("savings"));
    }

    #[test]
    fn test_account_directive_with_alias_sub() {
        let text = "\
account Assets:Checking
    alias chk
    note My checking account

2024/01/01 Test
    Assets:Checking     $10.00
    Expenses:A
";
        let mut journal = parse(text);
        assert!(journal.account_aliases.contains_key("chk"));
        let acct_id = journal.account_aliases["chk"];
        assert_eq!(journal.account_fullname(acct_id), "Assets:Checking");
        let acct_id2 = journal
            .accounts
            .find_account(journal.accounts.root_id(), "Assets:Checking", false)
            .unwrap();
        assert_eq!(
            journal.accounts.get(acct_id2).note,
            Some("My checking account".to_string())
        );
    }

    // -----------------------------------------------------------------------
    // Bucket / A directive
    // -----------------------------------------------------------------------

    #[test]
    fn test_bucket_directive() {
        let text = "\
bucket Assets:Checking

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert!(journal.bucket.is_some());
        let bucket_name = journal.account_fullname(journal.bucket.unwrap());
        assert_eq!(bucket_name, "Assets:Checking");
    }

    #[test]
    fn test_a_directive_bucket() {
        let text = "\
A Assets:Savings

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert!(journal.bucket.is_some());
        let bucket_name = journal.account_fullname(journal.bucket.unwrap());
        assert_eq!(bucket_name, "Assets:Savings");
    }

    #[test]
    fn test_account_default_sub_directive() {
        let text = "\
account Assets:Checking
    default

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert!(journal.bucket.is_some());
        let bucket_name = journal.account_fullname(journal.bucket.unwrap());
        assert_eq!(bucket_name, "Assets:Checking");
    }

    // -----------------------------------------------------------------------
    // Tag directive
    // -----------------------------------------------------------------------

    #[test]
    fn test_tag_directive() {
        let text = "\
tag Receipt

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.tag_declarations.len(), 1);
        assert_eq!(journal.tag_declarations[0], "Receipt");
    }

    #[test]
    fn test_tag_directive_multiple() {
        let text = "\
tag Receipt
tag Project

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.tag_declarations.len(), 2);
        assert_eq!(journal.tag_declarations[0], "Receipt");
        assert_eq!(journal.tag_declarations[1], "Project");
    }

    #[test]
    fn test_tag_directive_with_sub_directives() {
        let text = "\
tag Receipt
    check value =~ /receipt-.*/

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.tag_declarations.len(), 1);
        assert_eq!(journal.tag_declarations[0], "Receipt");
    }

    // -----------------------------------------------------------------------
    // Payee directive
    // -----------------------------------------------------------------------

    #[test]
    fn test_payee_directive() {
        let text = "\
payee Grocery Store

2024/01/01 Grocery Store
    Expenses:Food     $10.00
    Assets:Checking
";
        let journal = parse(text);
        assert_eq!(journal.payee_declarations.len(), 1);
        assert_eq!(journal.payee_declarations[0], "Grocery Store");
    }

    #[test]
    fn test_payee_directive_multiple() {
        let text = "\
payee Grocery Store
payee Coffee Shop

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.payee_declarations.len(), 2);
        assert_eq!(journal.payee_declarations[0], "Grocery Store");
        assert_eq!(journal.payee_declarations[1], "Coffee Shop");
    }

    #[test]
    fn test_payee_directive_with_sub_directives() {
        let text = "\
payee Grocery Store
    alias Groceries

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.payee_declarations.len(), 1);
        assert_eq!(journal.payee_declarations[0], "Grocery Store");
    }

    // -----------------------------------------------------------------------
    // Apply account / end apply account
    // -----------------------------------------------------------------------

    #[test]
    fn test_apply_account() {
        let text = "\
apply account Personal

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B

end apply account
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1);
        assert!(journal.apply_account_stack.is_empty());
    }

    #[test]
    fn test_apply_account_nested() {
        let text = "\
apply account Personal
apply account Checking

end apply account
end apply account

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert!(journal.apply_account_stack.is_empty());
    }

    #[test]
    fn test_apply_account_unclosed() {
        let text = "\
apply account Personal

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.apply_account_stack.len(), 1);
        assert_eq!(journal.apply_account_stack[0], "Personal");
    }

    // -----------------------------------------------------------------------
    // Apply tag / end apply tag
    // -----------------------------------------------------------------------

    #[test]
    fn test_apply_tag() {
        let text = "\
apply tag project

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B

end apply tag
";
        let journal = parse(text);
        assert!(journal.apply_tag_stack.is_empty());
    }

    #[test]
    fn test_apply_tag_nested() {
        let text = "\
apply tag project
apply tag urgent

end apply tag
end apply tag
";
        let journal = parse(text);
        assert!(journal.apply_tag_stack.is_empty());
    }

    #[test]
    fn test_apply_tag_unclosed() {
        let text = "\
apply tag project

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.apply_tag_stack.len(), 1);
        assert_eq!(journal.apply_tag_stack[0], "project");
    }

    // -----------------------------------------------------------------------
    // D default commodity directive
    // -----------------------------------------------------------------------

    #[test]
    fn test_default_commodity_directive() {
        let text = "\
D $1,000.00

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert!(journal.commodity_pool.default_commodity.is_some());
        let default_id = journal.commodity_pool.default_commodity.unwrap();
        let commodity = journal.commodity_pool.get(default_id);
        assert_eq!(commodity.symbol(), "$");
    }

    #[test]
    fn test_default_commodity_eur() {
        let text = "\
D 1.000,00 EUR

2024/01/01 Test
    Expenses:A     10.00 EUR
    Assets:B
";
        let journal = parse(text);
        assert!(journal.commodity_pool.default_commodity.is_some());
        let default_id = journal.commodity_pool.default_commodity.unwrap();
        let commodity = journal.commodity_pool.get(default_id);
        assert_eq!(commodity.symbol(), "EUR");
    }

    // -----------------------------------------------------------------------
    // N no-market directive
    // -----------------------------------------------------------------------

    #[test]
    fn test_no_market_directive() {
        let text = "\
N $

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.no_market_commodities.len(), 1);
        assert_eq!(journal.no_market_commodities[0], "$");
        let commodity_id = journal.commodity_pool.find("$").unwrap();
        let commodity = journal.commodity_pool.get(commodity_id);
        assert!(commodity.has_flags(crate::commodity::CommodityStyle::NOMARKET));
    }

    #[test]
    fn test_no_market_directive_multiple() {
        let text = "\
N $
N EUR

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.no_market_commodities.len(), 2);
        assert_eq!(journal.no_market_commodities[0], "$");
        assert_eq!(journal.no_market_commodities[1], "EUR");
    }

    // -----------------------------------------------------------------------
    // P price directive
    // -----------------------------------------------------------------------

    #[test]
    fn test_price_directive() {
        let text = "\
P 2024/01/01 AAPL $150.00

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.prices.len(), 1);
        let (date, symbol, amount) = &journal.prices[0];
        assert_eq!(*date, NaiveDate::from_ymd_opt(2024, 1, 1).unwrap());
        assert_eq!(symbol, "AAPL");
        assert!((amount.to_double().unwrap() - 150.0).abs() < 0.01);
        assert_eq!(amount.commodity(), Some("$"));
    }

    #[test]
    fn test_price_directive_multiple() {
        let text = "\
P 2024/01/01 AAPL $150.00
P 2024/02/01 AAPL $160.00

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.prices.len(), 2);
        let (date1, _, amt1) = &journal.prices[0];
        let (date2, _, amt2) = &journal.prices[1];
        assert_eq!(*date1, NaiveDate::from_ymd_opt(2024, 1, 1).unwrap());
        assert_eq!(*date2, NaiveDate::from_ymd_opt(2024, 2, 1).unwrap());
        assert!((amt1.to_double().unwrap() - 150.0).abs() < 0.01);
        assert!((amt2.to_double().unwrap() - 160.0).abs() < 0.01);
    }

    #[test]
    fn test_price_directive_dash_date() {
        let text = "\
P 2024-06-15 EUR $1.10

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.prices.len(), 1);
        let (date, symbol, _) = &journal.prices[0];
        assert_eq!(*date, NaiveDate::from_ymd_opt(2024, 6, 15).unwrap());
        assert_eq!(symbol, "EUR");
    }

    // -----------------------------------------------------------------------
    // Define directive
    // -----------------------------------------------------------------------

    #[test]
    fn test_define_directive() {
        let text = "\
define myvar=42

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.defines.get("myvar"), Some(&"42".to_string()));
    }

    #[test]
    fn test_define_directive_with_spaces() {
        let text = "\
define rate = 1.5

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.defines.get("rate"), Some(&"1.5".to_string()));
    }

    #[test]
    fn test_define_directive_expression() {
        let text = "\
define hourly_rate = 75.00
define monthly = hourly_rate * 160

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(
            journal.defines.get("hourly_rate"),
            Some(&"75.00".to_string())
        );
        assert_eq!(
            journal.defines.get("monthly"),
            Some(&"hourly_rate * 160".to_string())
        );
    }

    // -----------------------------------------------------------------------
    // Include directive (non-existent file errors)
    // -----------------------------------------------------------------------

    #[test]
    fn test_include_nonexistent_file_errors() {
        let text = "include /nonexistent/file.dat\n";
        let mut journal = Journal::new();
        let parser = TextualParser::new();
        let result = parser.parse_string(text, &mut journal);
        assert!(result.is_err());
    }

    // -----------------------------------------------------------------------
    // End / end comment
    // -----------------------------------------------------------------------

    #[test]
    fn test_end_comment_block() {
        let text = "\
comment
This entire block is a comment
It can span many lines
end comment

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn test_standalone_end_ignored() {
        let text = "\
end

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1);
    }

    // -----------------------------------------------------------------------
    // Unknown directives handled gracefully
    // -----------------------------------------------------------------------

    #[test]
    fn test_unknown_directive_skipped() {
        let text = "\
some_unknown_directive with args

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1);
    }

    #[test]
    fn test_c_directive_skipped() {
        let text = "\
C 1.00 Kb = 1024 bytes

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1);
    }

    // -----------------------------------------------------------------------
    // Combined directives test
    // -----------------------------------------------------------------------

    #[test]
    fn test_multiple_directives_combined() {
        let text = "\
; Preamble
Y 2024
D $1,000.00
N $
P 2024/01/01 AAPL $150.00
alias chk=Assets:Checking
bucket Assets:Checking
tag Receipt
payee Grocery Store
define rate=42

account Assets:Checking
    note Main checking
    alias checking

commodity $
    format $1,000.00

2024/01/01 * Grocery Store
    Expenses:Food     $42.50
    Assets:Checking
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1);
        assert_eq!(journal.default_year, Some(2024));
        assert!(journal.commodity_pool.default_commodity.is_some());
        assert_eq!(journal.no_market_commodities.len(), 1);
        assert_eq!(journal.prices.len(), 1);
        assert!(journal.account_aliases.contains_key("chk"));
        assert!(journal.account_aliases.contains_key("checking"));
        assert!(journal.bucket.is_some());
        assert_eq!(journal.tag_declarations.len(), 1);
        assert_eq!(journal.payee_declarations.len(), 1);
        assert_eq!(journal.defines.get("rate"), Some(&"42".to_string()));
    }

    // -----------------------------------------------------------------------
    // Test block
    // -----------------------------------------------------------------------

    #[test]
    fn test_test_block_skipped() {
        let text = "\
test expected output
    $42.50  Expenses:Food
end test

2024/01/01 Test
    Expenses:A     $10.00
    Assets:B
";
        let journal = parse(text);
        assert_eq!(journal.xacts.len(), 1);
    }
}
