import XCTest
@testable import muonledger

final class ParserTests: XCTestCase {

    override func setUp() {
        super.setUp()
        CommodityPool.resetCurrent()
    }

    override func tearDown() {
        CommodityPool.resetCurrent()
        super.tearDown()
    }

    // MARK: - Basic Transaction

    func testParseBasicTwoPostingTransaction() throws {
        let input = """
        2024-01-15 Grocery Store
            Expenses:Food              $50.00
            Assets:Checking
        """
        let parser = Parser()
        let count = try parser.parse(text: input)

        XCTAssertEqual(count, 1)
        XCTAssertEqual(parser.journal.transactions.count, 1)

        let xact = parser.journal.transactions[0]
        XCTAssertEqual(xact.payee, "Grocery Store")
        XCTAssertEqual(xact.posts.count, 2)

        let post0 = xact.posts[0]
        XCTAssertEqual(post0.account?.fullname, "Expenses:Food")
        XCTAssertNotNil(post0.amount)
        XCTAssertEqual(post0.amount?.quantity, Decimal(50))
        XCTAssertEqual(post0.amount?.commoditySymbol, "$")

        let post1 = xact.posts[1]
        XCTAssertEqual(post1.account?.fullname, "Assets:Checking")
        // Inferred amount: -$50.00
        XCTAssertNotNil(post1.amount)
        XCTAssertEqual(post1.amount?.quantity, Decimal(-50))
    }

    // MARK: - State Markers

    func testParseTransactionCleared() throws {
        let input = """
        2024-01-15 * Cleared transaction
            Expenses:Food              $25.00
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        XCTAssertEqual(parser.journal.transactions.count, 1)
        let xact = parser.journal.transactions[0]
        XCTAssertEqual(xact.state, .cleared)
        XCTAssertEqual(xact.payee, "Cleared transaction")
    }

    func testParseTransactionPending() throws {
        let input = """
        2024-01-15 ! Pending payment
            Expenses:Food              $25.00
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        XCTAssertEqual(parser.journal.transactions.count, 1)
        let xact = parser.journal.transactions[0]
        XCTAssertEqual(xact.state, .pending)
        XCTAssertEqual(xact.payee, "Pending payment")
    }

    // MARK: - Null Amount Inference

    func testParseNullAmountInference() throws {
        let input = """
        2024-01-15 Test
            Expenses:Food              $42.50
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        let xact = parser.journal.transactions[0]
        XCTAssertEqual(xact.posts.count, 2)

        // Second posting should have inferred amount
        let post1 = xact.posts[1]
        XCTAssertNotNil(post1.amount)
        XCTAssertEqual(post1.amount?.quantity, Decimal(string: "-42.5"))
    }

    // MARK: - Virtual Postings

    func testParseVirtualPostingParentheses() throws {
        let input = """
        2024-01-15 Budget
            (Budget:Savings)            $500.00
            (Budget:Emergency)          $200.00
        """
        let parser = Parser()
        try parser.parse(text: input)

        // Virtual postings don't need to balance, so both can have amounts
        let xact = parser.journal.transactions[0]
        XCTAssertEqual(xact.posts.count, 2)

        let post0 = xact.posts[0]
        XCTAssertTrue(post0.isVirtual)
        XCTAssertFalse(post0.isBalanceVirtual)
        XCTAssertEqual(post0.account?.fullname, "Budget:Savings")

        let post1 = xact.posts[1]
        XCTAssertTrue(post1.isVirtual)
        XCTAssertEqual(post1.account?.fullname, "Budget:Emergency")
    }

    func testParseVirtualPostingBrackets() throws {
        let input = """
        2024-01-15 Budget
            [Budget:Savings]            $500.00
            [Budget:Emergency]          $-500.00
        """
        let parser = Parser()
        try parser.parse(text: input)

        let xact = parser.journal.transactions[0]
        let post0 = xact.posts[0]
        XCTAssertTrue(post0.isBalanceVirtual)
        XCTAssertEqual(post0.account?.fullname, "Budget:Savings")
    }

    // MARK: - Cost @ and @@

    func testParseCostPerUnit() throws {
        let input = """
        2024-01-15 Forex
            Assets:Euro                100 EUR @ $1.10
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        let xact = parser.journal.transactions[0]
        let post0 = xact.posts[0]
        XCTAssertEqual(post0.account?.fullname, "Assets:Euro")
        XCTAssertEqual(post0.amount?.quantity, Decimal(100))
        XCTAssertEqual(post0.amount?.commoditySymbol, "EUR")
        // Cost = |100| * $1.10 = $110.00
        XCTAssertNotNil(post0.cost)
        XCTAssertEqual(post0.cost?.quantity, Decimal(110))
        XCTAssertEqual(post0.cost?.commoditySymbol, "$")
    }

    func testParseCostTotal() throws {
        let input = """
        2024-01-15 Forex
            Assets:Euro                100 EUR @@ $110.00
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        let xact = parser.journal.transactions[0]
        let post0 = xact.posts[0]
        XCTAssertNotNil(post0.cost)
        XCTAssertEqual(post0.cost?.quantity, Decimal(110))
        XCTAssertEqual(post0.cost?.commoditySymbol, "$")
    }

    // MARK: - Lot Annotation

    func testParseLotAnnotation() throws {
        let input = """
        2024-01-15 Buy Stock
            Assets:Brokerage           10 AAPL {$150.00}
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        let xact = parser.journal.transactions[0]
        let post0 = xact.posts[0]
        XCTAssertEqual(post0.amount?.quantity, Decimal(10))
        XCTAssertEqual(post0.amount?.commoditySymbol, "AAPL")
        // Lot price
        XCTAssertNotNil(post0.lotPrice)
        XCTAssertEqual(post0.lotPrice?.quantity, Decimal(150))
        XCTAssertEqual(post0.lotPrice?.commoditySymbol, "$")
        // Derived cost = |10| * $150 = $1500
        XCTAssertNotNil(post0.cost)
        XCTAssertEqual(post0.cost?.quantity, Decimal(1500))
    }

    // MARK: - Balance Assertion

    func testParseBalanceAssertion() throws {
        let input = """
        2024-01-15 Test
            Expenses:Food              $50.00
            Assets:Checking             = $950.00
        """
        let parser = Parser()
        try parser.parse(text: input)

        let xact = parser.journal.transactions[0]
        let post1 = xact.posts[1]
        XCTAssertEqual(post1.account?.fullname, "Assets:Checking")
        // The assigned amount is the assertion value
        XCTAssertNotNil(post1.assignedAmount)
        XCTAssertEqual(post1.assignedAmount?.quantity, Decimal(950))
        XCTAssertEqual(post1.assignedAmount?.commoditySymbol, "$")
        // The posting amount is nil until finalize infers it
        // After finalize (which addTransaction calls), it should be -$50.00
        XCTAssertNotNil(post1.amount)
        XCTAssertEqual(post1.amount?.quantity, Decimal(-50))
    }

    // MARK: - Alias Directive

    func testParseAliasDirective() throws {
        let input = """
        alias chk=Assets:Checking

        2024-01-15 Test
            Expenses:Food              $50.00
            chk
        """
        let parser = Parser()
        try parser.parse(text: input)

        XCTAssertEqual(parser.journal.transactions.count, 1)
        let xact = parser.journal.transactions[0]
        let post1 = xact.posts[1]
        XCTAssertEqual(post1.account?.fullname, "Assets:Checking")
    }

    // MARK: - Apply Account Directive

    func testParseApplyAccount() throws {
        let input = """
        apply account Assets

        2024-01-15 Test
            Checking                   $-50.00
            Savings                    $50.00

        end apply account
        """
        let parser = Parser()
        try parser.parse(text: input)

        XCTAssertEqual(parser.journal.transactions.count, 1)
        let xact = parser.journal.transactions[0]
        XCTAssertEqual(xact.posts[0].account?.fullname, "Assets:Checking")
        XCTAssertEqual(xact.posts[1].account?.fullname, "Assets:Savings")
    }

    // MARK: - Comment Block

    func testParseCommentBlock() throws {
        let input = """
        comment
        This is a multi-line comment.
        It should be completely ignored.
        end comment

        2024-01-15 Test
            Expenses:Food              $50.00
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        XCTAssertEqual(parser.journal.transactions.count, 1)
        XCTAssertEqual(parser.journal.transactions[0].payee, "Test")
    }

    // MARK: - Include Directive

    func testParseIncludeDirective() throws {
        // Create a temp file
        let tempDir = NSTemporaryDirectory()
        let includedFile = (tempDir as NSString).appendingPathComponent("included.ledger")
        let mainFile = (tempDir as NSString).appendingPathComponent("main.ledger")

        let includedContent = """
        2024-01-10 Included Transaction
            Expenses:Food              $25.00
            Assets:Checking
        """

        let mainContent = """
        include included.ledger

        2024-01-15 Main Transaction
            Expenses:Rent              $1000.00
            Assets:Checking
        """

        try includedContent.write(toFile: includedFile, atomically: true, encoding: .utf8)
        try mainContent.write(toFile: mainFile, atomically: true, encoding: .utf8)

        defer {
            try? FileManager.default.removeItem(atPath: includedFile)
            try? FileManager.default.removeItem(atPath: mainFile)
        }

        let parser = Parser()
        try parser.parse(file: mainFile)

        XCTAssertEqual(parser.journal.transactions.count, 2)
        XCTAssertEqual(parser.journal.transactions[0].payee, "Included Transaction")
        XCTAssertEqual(parser.journal.transactions[1].payee, "Main Transaction")
    }

    // MARK: - Price Directive

    func testParsePriceDirective() throws {
        let input = """
        P 2024-01-15 EUR $1.10

        2024-01-15 Test
            Expenses:Food              $50.00
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        // Price directive should not cause errors, and the transaction should parse
        XCTAssertEqual(parser.journal.transactions.count, 1)
    }

    // MARK: - Automated Transaction

    func testParseAutomatedTransaction() throws {
        let input = """
        = Expenses:Food
            (Budget:Food)              -1.0

        2024-01-15 Test
            Expenses:Food              $50.00
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        // The automated transaction should be parsed without error
        // and the regular transaction should parse normally
        XCTAssertEqual(parser.journal.transactions.count, 1)
        XCTAssertEqual(parser.journal.transactions[0].payee, "Test")
    }

    // MARK: - Periodic Transaction

    func testParsePeriodicTransaction() throws {
        let input = """
        ~ Monthly
            Expenses:Rent              $1000.00
            Assets:Checking

        2024-01-15 Test
            Expenses:Food              $50.00
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        // The periodic transaction should be parsed without error
        XCTAssertEqual(parser.journal.transactions.count, 1)
        XCTAssertEqual(parser.journal.transactions[0].payee, "Test")
    }

    // MARK: - Payee with | Note

    func testParsePayeeWithPipeNote() throws {
        let input = """
        2024-01-15 Store | Receipt #123
            Expenses:Food              $50.00
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        let xact = parser.journal.transactions[0]
        XCTAssertEqual(xact.payee, "Store")
        XCTAssertEqual(xact.note, "Receipt #123")
    }

    // MARK: - Date with / Separator

    func testParseDateWithSlash() throws {
        let input = """
        2024/01/15 Test
            Expenses:Food              $50.00
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        XCTAssertEqual(parser.journal.transactions.count, 1)
        let xact = parser.journal.transactions[0]
        XCTAssertEqual(xact.payee, "Test")
        // Verify the date was parsed correctly
        XCTAssertNotNil(xact.date)

        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let components = calendar.dateComponents([.year, .month, .day], from: xact.date!)
        XCTAssertEqual(components.year, 2024)
        XCTAssertEqual(components.month, 1)
        XCTAssertEqual(components.day, 15)
    }

    // MARK: - Comma Thousands Separator

    func testParseCommaThousandsSeparator() throws {
        let input = """
        2024-01-15 Test
            Expenses:Rent              $12,500.00
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        let xact = parser.journal.transactions[0]
        let post0 = xact.posts[0]
        XCTAssertEqual(post0.amount?.quantity, Decimal(12500))
    }

    // MARK: - Multiple Transactions

    func testParseMultipleTransactions() throws {
        let input = """
        2024-01-15 First
            Expenses:Food              $50.00
            Assets:Checking

        2024-01-16 Second
            Expenses:Rent              $1000.00
            Assets:Checking
        """
        let parser = Parser()
        let count = try parser.parse(text: input)

        XCTAssertEqual(count, 2)
        XCTAssertEqual(parser.journal.transactions.count, 2)
        XCTAssertEqual(parser.journal.transactions[0].payee, "First")
        XCTAssertEqual(parser.journal.transactions[1].payee, "Second")
    }

    // MARK: - Inline Comment on Posting

    func testParseInlineCommentOnPosting() throws {
        let input = """
        2024-01-15 Test
            Expenses:Food              $25.00  ; lunch
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        let xact = parser.journal.transactions[0]
        let post0 = xact.posts[0]
        XCTAssertEqual(post0.note, "lunch")
        XCTAssertEqual(post0.amount?.quantity, Decimal(25))
    }

    // MARK: - Comment Lines

    func testParseTopLevelComments() throws {
        let input = """
        ; This is a comment
        # This is also a comment

        2024-01-15 Test
            Expenses:Food              $50.00
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        XCTAssertEqual(parser.journal.transactions.count, 1)
    }

    // MARK: - Transaction with Metadata Comment

    func testParseTransactionMetadataComment() throws {
        let input = """
        2024-01-15 Test
            ; Payee: metadata on its own line
            Expenses:Food              $50.00
            Assets:Checking
        """
        let parser = Parser()
        try parser.parse(text: input)

        let xact = parser.journal.transactions[0]
        // The comment before any postings attaches to the transaction
        XCTAssertNotNil(xact.note)
        XCTAssertTrue(xact.note!.contains("Payee: metadata on its own line"))
    }

    // MARK: - Suffix Commodity

    func testParseSuffixCommodity() throws {
        let input = """
        2024-01-15 Test
            Assets:Euro                100 EUR
            Assets:Checking            -100 EUR
        """
        let parser = Parser()
        try parser.parse(text: input)

        let xact = parser.journal.transactions[0]
        let post0 = xact.posts[0]
        XCTAssertEqual(post0.amount?.quantity, Decimal(100))
        XCTAssertEqual(post0.amount?.commoditySymbol, "EUR")
    }
}
