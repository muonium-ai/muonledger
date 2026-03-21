"""Tests for CSV import / convert command.

Covers: CsvRules, parse_csv, format_transaction, auto_detect_columns,
clean_amount, parse_date, and the convert_command entry point.
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from muonledger.csv_import import (
    CsvRules,
    auto_detect_columns,
    clean_amount,
    format_transaction,
    format_transactions,
    parse_csv,
    parse_date,
)
from muonledger.commands.convert import convert_command


# ---------------------------------------------------------------------------
# clean_amount
# ---------------------------------------------------------------------------

class TestCleanAmount:
    def test_plain_number(self):
        assert clean_amount("123.45") == "123.45"

    def test_dollar_sign(self):
        assert clean_amount("$123.45") == "123.45"

    def test_commas(self):
        assert clean_amount("1,234.56") == "1234.56"

    def test_dollar_and_commas(self):
        assert clean_amount("$1,234.56") == "1234.56"

    def test_parentheses_negative(self):
        assert clean_amount("($50.00)") == "-50.00"

    def test_parentheses_with_currency(self):
        assert clean_amount("($1,234.56)") == "-1234.56"

    def test_negative_with_dollar(self):
        assert clean_amount("-$100.00") == "-100.00"

    def test_positive_sign(self):
        assert clean_amount("+$100.00") == "100.00"

    def test_empty_string(self):
        assert clean_amount("") == "0"

    def test_whitespace_only(self):
        assert clean_amount("   ") == "0"

    def test_euro_symbol(self):
        # Euro sign stripped as non-numeric
        assert clean_amount("\u20ac100.50") == "100.50"

    def test_trailing_minus(self):
        assert clean_amount("100.00-") == "-100.00"

    def test_integer(self):
        assert clean_amount("500") == "500"

    def test_negative_integer(self):
        assert clean_amount("-500") == "-500"


# ---------------------------------------------------------------------------
# parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_iso_format(self):
        assert parse_date("2024-01-15") == datetime(2024, 1, 15)

    def test_us_format(self):
        assert parse_date("01/15/2024") == datetime(2024, 1, 15)

    def test_explicit_format(self):
        assert parse_date("15-01-2024", "%d-%m-%Y") == datetime(2024, 1, 15)

    def test_compact_format(self):
        assert parse_date("20240115") == datetime(2024, 1, 15)

    def test_month_name(self):
        assert parse_date("Jan 15, 2024") == datetime(2024, 1, 15)

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError, match="Unable to parse date"):
            parse_date("not-a-date")

    def test_whitespace_trimmed(self):
        assert parse_date("  2024-01-15  ") == datetime(2024, 1, 15)

    def test_slash_ymd(self):
        assert parse_date("2024/03/20") == datetime(2024, 3, 20)


# ---------------------------------------------------------------------------
# auto_detect_columns
# ---------------------------------------------------------------------------

class TestAutoDetectColumns:
    def test_standard_headers(self):
        headers = ["Date", "Description", "Amount"]
        mapping = auto_detect_columns(headers)
        assert mapping["date"] == 0
        assert mapping["payee"] == 1
        assert mapping["amount"] == 2

    def test_case_insensitive(self):
        headers = ["DATE", "DESCRIPTION", "AMOUNT"]
        mapping = auto_detect_columns(headers)
        assert "date" in mapping
        assert "payee" in mapping
        assert "amount" in mapping

    def test_payee_as_payee(self):
        headers = ["Date", "Payee", "Amount"]
        mapping = auto_detect_columns(headers)
        assert mapping["payee"] == 1

    def test_debit_credit_columns(self):
        headers = ["Date", "Description", "Debit", "Credit"]
        mapping = auto_detect_columns(headers)
        assert mapping["debit"] == 2
        assert mapping["credit"] == 3

    def test_note_column(self):
        headers = ["Date", "Description", "Amount", "Note"]
        mapping = auto_detect_columns(headers)
        assert mapping["note"] == 3

    def test_no_match(self):
        headers = ["Col1", "Col2", "Col3"]
        mapping = auto_detect_columns(headers)
        assert mapping == {}

    def test_whitespace_in_headers(self):
        headers = [" Date ", " Description ", " Amount "]
        mapping = auto_detect_columns(headers)
        assert mapping["date"] == 0

    def test_merchant_maps_to_payee(self):
        headers = ["Date", "Merchant", "Amount"]
        mapping = auto_detect_columns(headers)
        assert mapping["payee"] == 1

    def test_withdrawal_maps_to_debit(self):
        headers = ["Date", "Payee", "Withdrawal", "Deposit"]
        mapping = auto_detect_columns(headers)
        assert mapping["debit"] == 2
        assert mapping["credit"] == 3

    def test_reference_maps_to_note(self):
        headers = ["Date", "Payee", "Amount", "Reference"]
        mapping = auto_detect_columns(headers)
        assert mapping["note"] == 3


# ---------------------------------------------------------------------------
# parse_csv — basic
# ---------------------------------------------------------------------------

class TestParseCsvBasic:
    def test_basic_with_headers(self):
        csv = "Date,Description,Amount\n2024-01-15,Grocery Store,50.00\n"
        txns = parse_csv(csv)
        assert len(txns) == 1
        assert txns[0]["payee"] == "Grocery Store"
        assert txns[0]["amount"] == "50.00"
        assert txns[0]["date"] == datetime(2024, 1, 15)

    def test_multiple_transactions(self):
        csv = (
            "Date,Description,Amount\n"
            "2024-01-15,Grocery Store,50.00\n"
            "2024-01-16,Gas Station,30.00\n"
            "2024-01-17,Restaurant,25.00\n"
        )
        txns = parse_csv(csv)
        assert len(txns) == 3
        assert txns[2]["payee"] == "Restaurant"

    def test_empty_input(self):
        assert parse_csv("") == []

    def test_header_only(self):
        assert parse_csv("Date,Description,Amount\n") == []

    def test_empty_rows_skipped(self):
        csv = "Date,Description,Amount\n2024-01-15,Store,10\n\n\n2024-01-16,Shop,20\n"
        txns = parse_csv(csv)
        assert len(txns) == 2

    def test_single_row(self):
        csv = "Date,Description,Amount\n2024-06-01,Coffee,5.50\n"
        txns = parse_csv(csv)
        assert len(txns) == 1
        assert txns[0]["amount"] == "5.50"


# ---------------------------------------------------------------------------
# parse_csv — field mapping
# ---------------------------------------------------------------------------

class TestParseCsvFieldMapping:
    def test_custom_index_mapping(self):
        csv = "2024-01-15,50.00,Grocery Store\n"
        rules = CsvRules(date_field=0, amount_field=1, payee_field=2)
        txns = parse_csv(csv, rules)
        assert len(txns) == 1
        assert txns[0]["payee"] == "Grocery Store"
        assert txns[0]["amount"] == "50.00"

    def test_string_field_mapping(self):
        csv = "Trans Date,Memo,Sum\n2024-01-15,Coffee,4.50\n"
        rules = CsvRules(date_field="Trans Date", payee_field="Memo", amount_field="Sum")
        txns = parse_csv(csv, rules)
        assert len(txns) == 1
        assert txns[0]["payee"] == "Coffee"

    def test_debit_credit_columns(self):
        csv = (
            "Date,Description,Debit,Credit\n"
            "2024-01-15,Grocery Store,50.00,\n"
            "2024-01-16,Salary,,2000.00\n"
        )
        txns = parse_csv(csv)
        assert len(txns) == 2
        # Debit: money out -> negative
        assert float(txns[0]["amount"]) == -50.00
        # Credit: money in -> positive
        assert float(txns[1]["amount"]) == 2000.00

    def test_account_field(self):
        csv = "Date,Description,Amount,Category\n2024-01-15,Coffee,5.00,Food:Coffee\n"
        rules = CsvRules(account_field="Category")
        txns = parse_csv(csv, rules)
        assert txns[0]["account"] == "Food:Coffee"

    def test_note_field(self):
        csv = "Date,Description,Amount,Reference\n2024-01-15,Store,10.00,REF123\n"
        rules = CsvRules(note_field="Reference")
        txns = parse_csv(csv, rules)
        assert txns[0]["note"] == "REF123"


# ---------------------------------------------------------------------------
# parse_csv — skip lines, date format, etc.
# ---------------------------------------------------------------------------

class TestParseCsvOptions:
    def test_skip_lines(self):
        csv = "Bank Statement Export\nGenerated: 2024-01-20\nDate,Description,Amount\n2024-01-15,Store,10.00\n"
        rules = CsvRules(skip_lines=2)
        txns = parse_csv(csv, rules)
        assert len(txns) == 1
        assert txns[0]["payee"] == "Store"

    def test_custom_date_format(self):
        csv = "Date,Description,Amount\n15/01/2024,Store,10.00\n"
        rules = CsvRules(date_format="%d/%m/%Y")
        txns = parse_csv(csv, rules)
        assert txns[0]["date"] == datetime(2024, 1, 15)

    def test_invert_amount(self):
        csv = "Date,Description,Amount\n2024-01-15,Store,50.00\n"
        rules = CsvRules(invert_amount=True)
        txns = parse_csv(csv, rules)
        assert float(txns[0]["amount"]) == -50.00

    def test_no_header_with_indices(self):
        csv = "2024-01-15,Coffee,4.50\n2024-01-16,Lunch,12.00\n"
        rules = CsvRules(date_field=0, payee_field=1, amount_field=2)
        txns = parse_csv(csv, rules)
        assert len(txns) == 2
        assert txns[0]["payee"] == "Coffee"

    def test_missing_date_skips_row(self):
        csv = "Date,Description,Amount\n,Store,10.00\n2024-01-16,Shop,20.00\n"
        txns = parse_csv(csv)
        assert len(txns) == 1
        assert txns[0]["payee"] == "Shop"


# ---------------------------------------------------------------------------
# parse_csv — amount handling
# ---------------------------------------------------------------------------

class TestParseCsvAmounts:
    def test_negative_amount(self):
        csv = "Date,Description,Amount\n2024-01-15,Refund,-25.00\n"
        txns = parse_csv(csv)
        assert txns[0]["amount"] == "-25.00"

    def test_currency_in_amount(self):
        csv = "Date,Description,Amount\n2024-01-15,Store,$50.00\n"
        txns = parse_csv(csv)
        assert txns[0]["amount"] == "50.00"

    def test_commas_in_amount(self):
        csv = 'Date,Description,Amount\n2024-01-15,Rent,"1,200.00"\n'
        txns = parse_csv(csv)
        assert txns[0]["amount"] == "1200.00"

    def test_parentheses_negative(self):
        csv = 'Date,Description,Amount\n2024-01-15,Fee,"($15.00)"\n'
        txns = parse_csv(csv)
        assert txns[0]["amount"] == "-15.00"

    def test_debit_only_column(self):
        csv = "Date,Description,Debit,Credit\n2024-01-15,Store,100.00,\n"
        txns = parse_csv(csv)
        assert float(txns[0]["amount"]) == -100.00

    def test_credit_only_column(self):
        csv = "Date,Description,Debit,Credit\n2024-01-15,Payment,,500.00\n"
        txns = parse_csv(csv)
        assert float(txns[0]["amount"]) == 500.00

    def test_both_debit_and_credit(self):
        csv = "Date,Description,Debit,Credit\n2024-01-15,Transfer,100.00,50.00\n"
        txns = parse_csv(csv)
        # net = credit - debit = 50 - 100 = -50
        assert float(txns[0]["amount"]) == -50.00


# ---------------------------------------------------------------------------
# parse_csv — quoted fields & edge cases
# ---------------------------------------------------------------------------

class TestParseCsvEdgeCases:
    def test_quoted_fields_with_commas(self):
        csv = 'Date,Description,Amount\n2024-01-15,"Smith, John",50.00\n'
        txns = parse_csv(csv)
        assert txns[0]["payee"] == "Smith, John"

    def test_quoted_fields_with_newlines(self):
        csv = 'Date,Description,Amount\n2024-01-15,"Multi\nline",50.00\n'
        txns = parse_csv(csv)
        assert len(txns) == 1
        assert "Multi" in txns[0]["payee"]

    def test_extra_columns_ignored(self):
        csv = "Date,Description,Amount,Extra1,Extra2\n2024-01-15,Store,50.00,foo,bar\n"
        txns = parse_csv(csv)
        assert len(txns) == 1
        assert txns[0]["amount"] == "50.00"

    def test_missing_payee_defaults(self):
        # No payee column at all with index mapping -> "Unknown"
        csv = "2024-01-15,50.00\n"
        rules = CsvRules(date_field=0, amount_field=1)
        txns = parse_csv(csv, rules)
        assert txns[0]["payee"] == "Unknown"

    def test_whitespace_in_cells(self):
        csv = "Date,Description,Amount\n 2024-01-15 , Coffee Shop , 5.50 \n"
        txns = parse_csv(csv)
        assert txns[0]["payee"] == "Coffee Shop"
        assert txns[0]["amount"] == "5.50"


# ---------------------------------------------------------------------------
# format_transaction
# ---------------------------------------------------------------------------

class TestFormatTransaction:
    def test_basic_format(self):
        txn = {
            "date": datetime(2024, 1, 15),
            "payee": "Grocery Store",
            "amount": "50.00",
            "account": "",
            "note": "",
        }
        result = format_transaction(txn)
        assert "2024/01/15 Grocery Store" in result
        assert "Expenses:Unknown  50.00" in result
        assert "Assets:Bank:Checking" in result

    def test_with_currency(self):
        txn = {
            "date": datetime(2024, 1, 15),
            "payee": "Store",
            "amount": "50.00",
            "account": "",
            "note": "",
        }
        result = format_transaction(txn, currency="$")
        assert "$50.00" in result

    def test_negative_with_currency(self):
        txn = {
            "date": datetime(2024, 1, 15),
            "payee": "Refund",
            "amount": "-25.00",
            "account": "",
            "note": "",
        }
        result = format_transaction(txn, currency="$")
        assert "-$25.00" in result

    def test_custom_accounts(self):
        txn = {
            "date": datetime(2024, 1, 15),
            "payee": "Coffee",
            "amount": "5.00",
            "account": "Food:Coffee",
            "note": "",
        }
        result = format_transaction(
            txn,
            default_account="Expenses:Other",
            bank_account="Assets:Checking",
        )
        assert "Food:Coffee" in result
        assert "Assets:Checking" in result
        # Should use the txn's own account, not default
        assert "Expenses:Other" not in result

    def test_with_note(self):
        txn = {
            "date": datetime(2024, 1, 15),
            "payee": "Store",
            "amount": "10.00",
            "account": "",
            "note": "REF123",
        }
        result = format_transaction(txn)
        assert "; REF123" in result

    def test_default_account_used_when_no_txn_account(self):
        txn = {
            "date": datetime(2024, 1, 15),
            "payee": "Store",
            "amount": "10.00",
            "account": "",
            "note": "",
        }
        result = format_transaction(txn, default_account="Expenses:Groceries")
        assert "Expenses:Groceries" in result


# ---------------------------------------------------------------------------
# format_transactions
# ---------------------------------------------------------------------------

class TestFormatTransactions:
    def test_empty_list(self):
        assert format_transactions([]) == ""

    def test_multiple_transactions(self):
        txns = [
            {"date": datetime(2024, 1, 15), "payee": "Store", "amount": "50.00", "account": "", "note": ""},
            {"date": datetime(2024, 1, 16), "payee": "Coffee", "amount": "5.00", "account": "", "note": ""},
        ]
        result = format_transactions(txns)
        assert "2024/01/15 Store" in result
        assert "2024/01/16 Coffee" in result
        # Separated by blank line
        assert "\n\n" in result

    def test_ends_with_newline(self):
        txns = [{"date": datetime(2024, 1, 15), "payee": "Store", "amount": "10.00", "account": "", "note": ""}]
        result = format_transactions(txns)
        assert result.endswith("\n")


# ---------------------------------------------------------------------------
# convert_command
# ---------------------------------------------------------------------------

class TestConvertCommand:
    def test_basic_file(self, tmp_path):
        csv_file = tmp_path / "bank.csv"
        csv_file.write_text("Date,Description,Amount\n2024-01-15,Grocery Store,50.00\n")
        result = convert_command(csv_file=str(csv_file))
        assert "2024/01/15 Grocery Store" in result
        assert "Expenses:Unknown" in result
        assert "Assets:Bank:Checking" in result

    def test_with_rules_dict(self, tmp_path):
        csv_file = tmp_path / "bank.csv"
        csv_file.write_text("Date,Description,Amount\n2024-01-15,Coffee,4.50\n")
        result = convert_command(
            csv_file=str(csv_file),
            rules={
                "default_account": "Expenses:Food",
                "bank_account": "Assets:Checking",
                "currency": "$",
            },
        )
        assert "Expenses:Food" in result
        assert "Assets:Checking" in result
        assert "$4.50" in result

    def test_with_rules_object(self, tmp_path):
        csv_file = tmp_path / "bank.csv"
        csv_file.write_text("Date,Payee,Amount\n2024-01-15,Store,10.00\n")
        rules = CsvRules(default_account="Expenses:Shopping", currency="$")
        result = convert_command(csv_file=str(csv_file), rules=rules)
        assert "Expenses:Shopping" in result
        assert "$10.00" in result

    def test_argv_mode(self, tmp_path):
        csv_file = tmp_path / "bank.csv"
        csv_file.write_text("Date,Description,Amount\n2024-01-15,Store,20.00\n")
        result = convert_command(argv=[str(csv_file), "--currency", "$", "--account", "Assets:Savings"])
        assert "$20.00" in result
        assert "Assets:Savings" in result

    def test_empty_file(self, tmp_path):
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("")
        result = convert_command(csv_file=str(csv_file))
        assert result == ""

    def test_no_csv_file(self):
        result = convert_command(csv_file=None)
        assert result == ""

    def test_invert_via_argv(self, tmp_path):
        csv_file = tmp_path / "bank.csv"
        csv_file.write_text("Date,Description,Amount\n2024-01-15,Store,50.00\n")
        result = convert_command(argv=[str(csv_file), "--invert"])
        assert "-50.00" in result

    def test_skip_lines_via_argv(self, tmp_path):
        csv_file = tmp_path / "bank.csv"
        csv_file.write_text("Header junk\nMore junk\nDate,Description,Amount\n2024-01-15,Store,10.00\n")
        result = convert_command(argv=[str(csv_file), "--skip-lines", "2"])
        assert "Store" in result

    def test_full_output_format(self, tmp_path):
        csv_file = tmp_path / "bank.csv"
        csv_file.write_text(
            "Date,Description,Amount\n"
            "2024-01-15,Grocery Store,50.00\n"
            "2024-01-16,Gas Station,30.00\n"
        )
        result = convert_command(csv_file=str(csv_file), rules={"currency": "$"})
        lines = result.strip().split("\n")
        # First transaction
        assert lines[0] == "2024/01/15 Grocery Store"
        assert "Expenses:Unknown  $50.00" in lines[1]
        assert "Assets:Bank:Checking" in lines[2]
        # Blank line separator
        assert lines[3] == ""
        # Second transaction
        assert lines[4] == "2024/01/16 Gas Station"


# ---------------------------------------------------------------------------
# CsvRules defaults
# ---------------------------------------------------------------------------

class TestCsvRules:
    def test_defaults(self):
        r = CsvRules()
        assert r.date_field is None
        assert r.default_account == "Expenses:Unknown"
        assert r.bank_account == "Assets:Bank:Checking"
        assert r.currency == ""
        assert r.skip_lines == 0
        assert r.invert_amount is False

    def test_custom_fields(self):
        r = CsvRules(date_field=0, payee_field=1, currency="$")
        assert r.date_field == 0
        assert r.payee_field == 1
        assert r.currency == "$"
