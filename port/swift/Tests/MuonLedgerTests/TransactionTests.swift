import XCTest
@testable import muonledger

final class TransactionTests: XCTestCase {

    override func setUp() {
        super.setUp()
        CommodityPool.resetCurrent()
    }

    override func tearDown() {
        CommodityPool.resetCurrent()
        super.tearDown()
    }

    // MARK: - Balance type tests

    func testBalanceAddSameCommodity() throws {
        let pool = CommodityPool.getCurrent()
        let usd = pool.findOrCreate("$")
        let a = Amount(Decimal(100), precision: 2, commodity: usd)
        let b = Amount(Decimal(50), precision: 2, commodity: usd)

        var bal = Balance(a)
        bal.add(b)

        XCTAssertTrue(bal.isSingleCommodity)
        XCTAssertEqual(bal.singleAmount, Amount(Decimal(150), precision: 2, commodity: usd))
    }

    func testBalanceAddDifferentCommodity() throws {
        let pool = CommodityPool.getCurrent()
        let usd = pool.findOrCreate("$")
        let eur = pool.findOrCreate("EUR")
        let a = Amount(Decimal(100), precision: 2, commodity: usd)
        let b = Amount(Decimal(200), precision: 2, commodity: eur)

        var bal = Balance(a)
        bal.add(b)

        XCTAssertFalse(bal.isSingleCommodity)
        XCTAssertEqual(bal.commodityCount, 2)
        XCTAssertNil(bal.singleAmount)
    }

    func testBalanceSubtractToZero() throws {
        let pool = CommodityPool.getCurrent()
        let usd = pool.findOrCreate("$")
        let a = Amount(Decimal(100), precision: 2, commodity: usd)
        let b = Amount(Decimal(100), precision: 2, commodity: usd)

        var bal = Balance(a)
        bal.subtract(b)

        XCTAssertTrue(bal.isEmpty)
        XCTAssertTrue(bal.isZero)
    }

    func testBalanceNegate() throws {
        let pool = CommodityPool.getCurrent()
        let usd = pool.findOrCreate("$")
        let a = Amount(Decimal(100), precision: 2, commodity: usd)

        let bal = Balance(a)
        let neg = bal.negated()

        let expected = Amount(Decimal(-100), precision: 2, commodity: usd)
        XCTAssertEqual(neg.singleAmount, expected)
    }

    // MARK: - Value type tests

    func testValueEmpty() {
        let v = Value.empty
        XCTAssertTrue(v.isNull)
        XCTAssertTrue(v.isZero)
    }

    func testValueAddSameCommodity() throws {
        let pool = CommodityPool.getCurrent()
        let usd = pool.findOrCreate("$")
        let a = Value.amount(Amount(Decimal(100), precision: 2, commodity: usd))
        let b = Value.amount(Amount(Decimal(50), precision: 2, commodity: usd))

        let result = a + b
        guard case .amount(let amt) = result else {
            XCTFail("Expected .amount, got \(result)")
            return
        }
        XCTAssertEqual(amt.quantity, Decimal(150))
    }

    func testValueAddDifferentCommodityPromotes() throws {
        let pool = CommodityPool.getCurrent()
        let usd = pool.findOrCreate("$")
        let eur = pool.findOrCreate("EUR")
        let a = Value.amount(Amount(Decimal(100), precision: 2, commodity: usd))
        let b = Value.amount(Amount(Decimal(200), precision: 2, commodity: eur))

        let result = a + b
        guard case .balance(let bal) = result else {
            XCTFail("Expected .balance, got \(result)")
            return
        }
        XCTAssertEqual(bal.commodityCount, 2)
    }

    func testValueAddEmpty() {
        let v = Value.amount(Amount(42))
        let result = Value.empty + v
        guard case .amount(let amt) = result else {
            XCTFail("Expected .amount")
            return
        }
        XCTAssertEqual(amt.quantity, Decimal(42))
    }

    // MARK: - Transaction tests

    func testTwoPostingsBalance() throws {
        let pool = CommodityPool.getCurrent()
        let usd = pool.findOrCreate("$")

        let root = Account()
        let expenses = Account(parent: root, name: "Expenses")
        let checking = Account(parent: root, name: "Assets")

        let xact = Xact(payee: "Grocery Store")
        let p1 = Post(account: expenses, amount: Amount(Decimal(42.50), precision: 2, commodity: usd))
        let p2 = Post(account: checking, amount: Amount(Decimal(-42.50), precision: 2, commodity: usd))
        xact.addPost(p1)
        xact.addPost(p2)

        XCTAssertTrue(try xact.finalize())
    }

    func testNullAmountInference() throws {
        let pool = CommodityPool.getCurrent()
        let usd = pool.findOrCreate("$")

        let root = Account()
        let expenses = Account(parent: root, name: "Expenses")
        let checking = Account(parent: root, name: "Assets")

        let xact = Xact(payee: "Grocery Store")
        let p1 = Post(account: expenses, amount: Amount(Decimal(42.50), precision: 2, commodity: usd))
        let p2 = Post(account: checking)  // nil amount
        xact.addPost(p1)
        xact.addPost(p2)

        XCTAssertTrue(try xact.finalize())
        XCTAssertNotNil(p2.amount)
        XCTAssertEqual(p2.amount!.quantity, Decimal(-42.50))
        XCTAssertEqual(p2.amount!.commoditySymbol, "$")
    }

    func testTransactionDoesNotBalanceThrows() throws {
        let pool = CommodityPool.getCurrent()
        let usd = pool.findOrCreate("$")

        let root = Account()
        let expenses = Account(parent: root, name: "Expenses")
        let checking = Account(parent: root, name: "Assets")

        let xact = Xact(payee: "Bad Transaction")
        let p1 = Post(account: expenses, amount: Amount(Decimal(100), precision: 2, commodity: usd))
        let p2 = Post(account: checking, amount: Amount(Decimal(-50), precision: 2, commodity: usd))
        xact.addPost(p1)
        xact.addPost(p2)

        XCTAssertThrowsError(try xact.finalize()) { error in
            guard let txnError = error as? TransactionError else {
                XCTFail("Expected TransactionError, got \(error)")
                return
            }
            if case .doesNotBalance(let msg) = txnError {
                XCTAssertTrue(msg.contains("does not balance"))
            } else {
                XCTFail("Expected doesNotBalance error")
            }
        }
    }

    func testMultiCommodityImplicitExchange() throws {
        let pool = CommodityPool.getCurrent()
        let usd = pool.findOrCreate("$")
        let eur = pool.findOrCreate("EUR")

        let root = Account()
        let assets = Account(parent: root, name: "Assets")
        let broker = Account(parent: root, name: "Broker")

        let xact = Xact(payee: "Currency Exchange")
        let p1 = Post(account: assets, amount: Amount(Decimal(-100), precision: 2, commodity: usd))
        let p2 = Post(account: broker, amount: Amount(Decimal(85), precision: 2, commodity: eur))
        xact.addPost(p1)
        xact.addPost(p2)

        // Multi-commodity with all explicit amounts: implicit exchange, should not throw
        XCTAssertTrue(try xact.finalize())
    }

    func testVirtualPostingsBalanceSeparately() throws {
        let pool = CommodityPool.getCurrent()
        let usd = pool.findOrCreate("$")

        let root = Account()
        let expenses = Account(parent: root, name: "Expenses")
        let checking = Account(parent: root, name: "Assets")
        let budget = Account(parent: root, name: "Budget")
        let budgetFood = Account(parent: root, name: "Budget:Food")

        // Real postings balance
        let xact = Xact(payee: "Grocery Store")
        let p1 = Post(account: expenses, amount: Amount(Decimal(42.50), precision: 2, commodity: usd))
        let p2 = Post(account: checking, amount: Amount(Decimal(-42.50), precision: 2, commodity: usd))
        xact.addPost(p1)
        xact.addPost(p2)

        // Balanced-virtual postings balance separately
        let p3 = Post(account: budget, amount: Amount(Decimal(42.50), precision: 2, commodity: usd))
        p3.makeBalanceVirtual()
        let p4 = Post(account: budgetFood, amount: Amount(Decimal(-42.50), precision: 2, commodity: usd))
        p4.makeBalanceVirtual()
        xact.addPost(p3)
        xact.addPost(p4)

        XCTAssertTrue(try xact.finalize())
    }

    func testVirtualPostingsDoNotAffectRealBalance() throws {
        let pool = CommodityPool.getCurrent()
        let usd = pool.findOrCreate("$")

        let root = Account()
        let expenses = Account(parent: root, name: "Expenses")
        let checking = Account(parent: root, name: "Assets")
        let memo = Account(parent: root, name: "Memo")

        let xact = Xact(payee: "Test")
        let p1 = Post(account: expenses, amount: Amount(Decimal(100), precision: 2, commodity: usd))
        let p2 = Post(account: checking, amount: Amount(Decimal(-100), precision: 2, commodity: usd))
        xact.addPost(p1)
        xact.addPost(p2)

        // Plain virtual posting -- not balance-checked at all
        let p3 = Post(account: memo, amount: Amount(Decimal(999), precision: 2, commodity: usd))
        p3.makeVirtual()
        xact.addPost(p3)

        // Should still finalize successfully because virtual postings are ignored
        XCTAssertTrue(try xact.finalize())
    }

    // MARK: - Journal tests

    func testJournalAddTransaction() throws {
        let pool = CommodityPool.getCurrent()
        let usd = pool.findOrCreate("$")

        let journal = Journal()
        let expenses = journal.findOrCreateAccount("Expenses:Food")
        let checking = journal.findOrCreateAccount("Assets:Checking")

        let xact = Xact(payee: "Grocery Store")
        let p1 = Post(account: expenses, amount: Amount(Decimal(42.50), precision: 2, commodity: usd))
        let p2 = Post(account: checking, amount: Amount(Decimal(-42.50), precision: 2, commodity: usd))
        xact.addPost(p1)
        xact.addPost(p2)

        XCTAssertTrue(try journal.addTransaction(xact))
        XCTAssertEqual(journal.count, 1)
    }

    func testJournalFindOrCreateAccount() {
        let journal = Journal()
        let acct = journal.findOrCreateAccount("Expenses:Food:Dining")
        XCTAssertEqual(acct.fullname, "Expenses:Food:Dining")

        // Same path returns same account
        let acct2 = journal.findOrCreateAccount("Expenses:Food:Dining")
        XCTAssertTrue(acct === acct2)
    }

    func testJournalAliases() {
        let journal = Journal()
        journal.aliases["Food"] = "Expenses:Food:Dining"

        let acct = journal.findOrCreateAccount("Food")
        XCTAssertEqual(acct.fullname, "Expenses:Food:Dining")
    }

    // MARK: - Item / Post property tests

    func testItemStateAndFlags() {
        let item = Item()
        XCTAssertEqual(item.state, .uncleared)
        XCTAssertTrue(item.hasFlags(.normal))
        XCTAssertFalse(item.hasFlags(.generated))

        item.state = .cleared
        XCTAssertEqual(item.state, .cleared)

        item.addFlags(.generated)
        XCTAssertTrue(item.hasFlags(.generated))

        item.dropFlags(.generated)
        XCTAssertFalse(item.hasFlags(.generated))
    }

    func testItemMetadata() {
        let item = Item()
        XCTAssertFalse(item.hasTag("Payee"))

        item.setTag("Payee", value: "Test")
        XCTAssertTrue(item.hasTag("Payee"))
        XCTAssertEqual(item.getTag("Payee") as? String, "Test")
    }

    func testPostVirtualFlags() {
        let post = Post()
        XCTAssertFalse(post.isVirtual)
        XCTAssertFalse(post.isBalanceVirtual)

        post.makeVirtual()
        XCTAssertTrue(post.isVirtual)
        XCTAssertFalse(post.isBalanceVirtual)

        let post2 = Post()
        post2.makeBalanceVirtual()
        XCTAssertFalse(post2.isVirtual)  // isVirtual excludes mustBalance
        XCTAssertTrue(post2.isBalanceVirtual)
    }

    // MARK: - Lot annotation tests

    func testLotAnnotationDerivesCost() throws {
        let pool = CommodityPool.getCurrent()
        let aapl = pool.findOrCreate("AAPL")
        let usd = pool.findOrCreate("$")

        let root = Account()
        let broker = Account(parent: root, name: "Broker")
        let checking = Account(parent: root, name: "Checking")

        let xact = Xact(payee: "Buy Stock")
        // Buy 10 AAPL {$150.00}
        let p1 = Post(account: broker, amount: Amount(Decimal(10), precision: 0, commodity: aapl))
        p1.lotPrice = Amount(Decimal(150), precision: 2, commodity: usd)
        // Checking pays $-1500
        let p2 = Post(account: checking, amount: Amount(Decimal(-1500), precision: 2, commodity: usd))
        xact.addPost(p1)
        xact.addPost(p2)

        XCTAssertTrue(try xact.finalize())
        // cost should have been derived: 10 * $150 = $1500
        XCTAssertNotNil(p1.cost)
        XCTAssertEqual(p1.cost!.quantity, Decimal(1500))
        XCTAssertEqual(p1.cost!.commoditySymbol, "$")
    }
}
