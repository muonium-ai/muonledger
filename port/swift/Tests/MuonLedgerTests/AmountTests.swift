import XCTest
@testable import muonledger

final class AmountTests: XCTestCase {

    override func setUp() {
        super.setUp()
        CommodityPool.resetCurrent()
    }

    override func tearDown() {
        CommodityPool.resetCurrent()
        super.tearDown()
    }

    // MARK: - Creation

    func testNullAmount() {
        let amt = Amount()
        XCTAssertTrue(amt.isNull)
        XCTAssertEqual(amt.description, "<null>")
    }

    func testIntegerAmount() {
        let amt = Amount(42)
        XCTAssertFalse(amt.isNull)
        XCTAssertEqual(amt.quantity, Decimal(42))
        XCTAssertFalse(amt.hasCommodity)
    }

    func testDecimalAmount() {
        let amt = Amount(Decimal(string: "50.25")!, precision: 2)
        XCTAssertEqual(amt.quantityString, "50.25")
    }

    func testParseWithPrefixCommodity() throws {
        let amt = try Amount(parsing: "$50.00")
        XCTAssertEqual(amt.quantity, Decimal(string: "50.00"))
        XCTAssertEqual(amt.commoditySymbol, "$")
        XCTAssertTrue(amt.hasCommodity)
        XCTAssertEqual(amt.toString(), "$50.00")
    }

    func testParseWithSuffixCommodity() throws {
        let amt = try Amount(parsing: "100 EUR")
        XCTAssertEqual(amt.quantity, Decimal(100))
        XCTAssertEqual(amt.commoditySymbol, "EUR")
        XCTAssertEqual(amt.toString(), "100 EUR")
    }

    func testParseNegative() throws {
        let amt = try Amount(parsing: "$-15.00")
        XCTAssertTrue(amt.isNegative)
        XCTAssertEqual(amt.toString(), "$-15.00")
    }

    func testParseNegativePrefix() throws {
        let amt = try Amount(parsing: "-$15.00")
        XCTAssertTrue(amt.isNegative)
        XCTAssertEqual(amt.toString(), "$-15.00")
    }

    func testParseThousandsSeparator() throws {
        let amt = try Amount(parsing: "$12,500.00")
        XCTAssertEqual(amt.quantity, Decimal(string: "12500.00"))
        XCTAssertEqual(amt.toString(), "$12,500.00")
    }

    // MARK: - Arithmetic: Addition

    func testAddSameCommodity() throws {
        let a = try Amount(parsing: "$10.00")
        let b = try Amount(parsing: "$20.00")
        let c = a + b
        XCTAssertEqual(c.quantity, Decimal(30))
        XCTAssertEqual(c.commoditySymbol, "$")
    }

    func testAddNoCommodity() {
        let a = Amount(10)
        let b = Amount(20)
        let c = a + b
        XCTAssertEqual(c.quantity, Decimal(30))
    }

    // MARK: - Arithmetic: Subtraction

    func testSubtractSameCommodity() throws {
        let a = try Amount(parsing: "$50.00")
        let b = try Amount(parsing: "$20.00")
        let c = a - b
        XCTAssertEqual(c.quantity, Decimal(30))
        XCTAssertEqual(c.commoditySymbol, "$")
    }

    func testSubtractResultNegative() throws {
        let a = try Amount(parsing: "$10.00")
        let b = try Amount(parsing: "$25.00")
        let c = a - b
        XCTAssertTrue(c.isNegative)
        XCTAssertEqual(c.quantity, Decimal(-15))
    }

    // MARK: - Arithmetic: Multiplication

    func testMultiplyByScalar() throws {
        let a = try Amount(parsing: "$10.00")
        let b = a * 3
        XCTAssertEqual(b.quantity, Decimal(30))
        XCTAssertEqual(b.commoditySymbol, "$")
    }

    func testMultiplyByAmountScalar() throws {
        let a = try Amount(parsing: "$10.00")
        let b = Amount(3)
        let c = a * b
        XCTAssertEqual(c.quantity, Decimal(30))
    }

    // MARK: - Negation and abs

    func testNegation() throws {
        let a = try Amount(parsing: "$50.00")
        let b = -a
        XCTAssertTrue(b.isNegative)
        XCTAssertEqual(b.quantity, Decimal(-50))
    }

    func testDoubleNegation() throws {
        let a = try Amount(parsing: "$50.00")
        let b = -(-a)
        XCTAssertEqual(b.quantity, Decimal(50))
    }

    func testAbs() throws {
        let a = try Amount(parsing: "-$50.00")
        let b = a.abs()
        XCTAssertTrue(b.isPositive)
        XCTAssertEqual(b.quantity, Decimal(50))
    }

    func testAbsPositive() throws {
        let a = try Amount(parsing: "$50.00")
        let b = a.abs()
        XCTAssertEqual(b.quantity, Decimal(50))
    }

    // MARK: - isZero

    func testIsZero() {
        let a = Amount(0)
        XCTAssertTrue(a.isZero)
        XCTAssertTrue(a.isRealZero)
    }

    func testIsNotZero() {
        let a = Amount(42)
        XCTAssertFalse(a.isZero)
        XCTAssertTrue(a.isNonZero)
    }

    func testIsZeroParsed() throws {
        let a = try Amount(parsing: "$0.00")
        XCTAssertTrue(a.isZero)
    }

    // MARK: - Comparison

    func testEquality() throws {
        let a = try Amount(parsing: "$10.00")
        let b = try Amount(parsing: "$10.00")
        XCTAssertEqual(a, b)
    }

    func testInequality() throws {
        let a = try Amount(parsing: "$10.00")
        let b = try Amount(parsing: "$20.00")
        XCTAssertNotEqual(a, b)
    }

    func testLessThan() throws {
        let a = try Amount(parsing: "$10.00")
        let b = try Amount(parsing: "$20.00")
        XCTAssertTrue(a < b)
        XCTAssertFalse(b < a)
    }

    func testGreaterThan() throws {
        let a = try Amount(parsing: "$20.00")
        let b = try Amount(parsing: "$10.00")
        XCTAssertTrue(a > b)
    }

    // MARK: - Formatting

    func testFormatPrefix() throws {
        let a = try Amount(parsing: "$100.00")
        XCTAssertEqual(a.toString(), "$100.00")
    }

    func testFormatSuffix() throws {
        let a = try Amount(parsing: "100.00 EUR")
        XCTAssertEqual(a.toString(), "100.00 EUR")
    }

    func testFormatNegativePrefix() throws {
        let a = try Amount(parsing: "-$15.00")
        XCTAssertEqual(a.toString(), "$-15.00")
    }

    func testFormatNoCommodity() {
        let a = Amount(42)
        XCTAssertEqual(a.toString(), "42")
    }

    func testFormatDecimal() {
        let a = Amount(Decimal(string: "3.14")!, precision: 2)
        XCTAssertEqual(a.quantityString, "3.14")
    }

    // MARK: - Sign tests

    func testSignPositive() {
        let a = Amount(42)
        XCTAssertEqual(a.sign, 1)
        XCTAssertTrue(a.isPositive)
        XCTAssertFalse(a.isNegative)
    }

    func testSignNegative() {
        let a = Amount(-10)
        XCTAssertEqual(a.sign, -1)
        XCTAssertTrue(a.isNegative)
        XCTAssertFalse(a.isPositive)
    }

    func testSignZero() {
        let a = Amount(0)
        XCTAssertEqual(a.sign, 0)
        XCTAssertFalse(a.isPositive)
        XCTAssertFalse(a.isNegative)
    }

    // MARK: - Number (strip commodity)

    func testNumber() throws {
        let a = try Amount(parsing: "$50.00")
        let b = a.number()
        XCTAssertFalse(b.hasCommodity)
        XCTAssertEqual(b.quantity, Decimal(50))
    }

    // MARK: - Rounding

    func testRoundedTo() {
        let a = Amount(Decimal(string: "3.14159")!, precision: 5)
        let b = a.roundedTo(2)
        XCTAssertEqual(b.quantityString, "3.14")
    }
}
