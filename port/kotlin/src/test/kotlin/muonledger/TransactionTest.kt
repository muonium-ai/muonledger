package muonledger

import java.math.BigDecimal
import java.time.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class TransactionTest {

    // ---- Balance tests ------------------------------------------------------

    @Test
    fun `Balance add same commodity`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val bal = Balance()
        bal.add(Amount.of(BigDecimal("100.00"), usd))
        bal.add(Amount.of(BigDecimal("50.00"), usd))
        assertEquals(1, bal.commodityCount)
        assertTrue(bal.isSingleCommodity)
        val single = bal.singleAmount
        assertNotNull(single)
        assertEquals(Amount.of(BigDecimal("150.00"), usd), single)
    }

    @Test
    fun `Balance add different commodities`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val eur = CommodityPool.findOrCreate("EUR")
        val bal = Balance()
        bal.add(Amount.of(BigDecimal("100.00"), usd))
        bal.add(Amount.of(BigDecimal("50.00"), eur))
        assertEquals(2, bal.commodityCount)
        assertFalse(bal.isSingleCommodity)
        assertNull(bal.singleAmount)
    }

    @Test
    fun `Balance subtract to zero removes entry`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val bal = Balance()
        bal.add(Amount.of(BigDecimal("100.00"), usd))
        bal.subtract(Amount.of(BigDecimal("100.00"), usd))
        assertTrue(bal.isZero)
        assertTrue(bal.isEmpty)
    }

    @Test
    fun `Balance operators`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val b1 = Balance(Amount.of(BigDecimal("100.00"), usd))
        val b2 = Balance(Amount.of(BigDecimal("30.00"), usd))
        val sum = b1 + b2
        assertEquals(Amount.of(BigDecimal("130.00"), usd), sum.singleAmount)
        val diff = b1 - b2
        assertEquals(Amount.of(BigDecimal("70.00"), usd), diff.singleAmount)
    }

    @Test
    fun `Balance negate`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val bal = Balance(Amount.of(BigDecimal("100.00"), usd))
        val neg = -bal
        assertEquals(Amount.of(BigDecimal("-100.00"), usd), neg.singleAmount)
    }

    // ---- Value tests --------------------------------------------------------

    @Test
    fun `Value Empty is zero`() {
        assertTrue(Value.Empty.isZero)
        assertTrue(Value.Empty.isNull)
    }

    @Test
    fun `Value AmountValue add same commodity`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val v1 = Value.AmountValue(Amount.of(BigDecimal("10.00"), usd))
        val v2 = Value.AmountValue(Amount.of(BigDecimal("20.00"), usd))
        val sum = v1 + v2
        assertTrue(sum is Value.AmountValue)
        assertEquals(Amount.of(BigDecimal("30.00"), usd), (sum as Value.AmountValue).amount)
    }

    @Test
    fun `Value add different commodities promotes to BalanceValue`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val eur = CommodityPool.findOrCreate("EUR")
        val v1 = Value.AmountValue(Amount.of(BigDecimal("10.00"), usd))
        val v2 = Value.AmountValue(Amount.of(BigDecimal("20.00"), eur))
        val sum = v1 + v2
        assertTrue(sum is Value.BalanceValue)
    }

    @Test
    fun `Value negate`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val v = Value.AmountValue(Amount.of(BigDecimal("42.00"), usd))
        val neg = -v
        assertTrue(neg is Value.AmountValue)
        assertEquals(Amount.of(BigDecimal("-42.00"), usd), (neg as Value.AmountValue).amount)
    }

    // ---- Transaction tests --------------------------------------------------

    @Test
    fun `Transaction with two postings balances`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val root = Account()
        val expenses = root.findAccount("Expenses:Food")!!
        val checking = root.findAccount("Assets:Checking")!!

        val xact = Xact(date = LocalDate.of(2024, 1, 15), payee = "Grocery Store")
        xact.addPost(Post(account = expenses, amount = Amount.of(BigDecimal("42.50"), usd)))
        xact.addPost(Post(account = checking, amount = Amount.of(BigDecimal("-42.50"), usd)))
        xact.finalize() // Should not throw
    }

    @Test
    fun `Null amount inference`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val root = Account()
        val expenses = root.findAccount("Expenses:Food")!!
        val checking = root.findAccount("Assets:Checking")!!

        val xact = Xact(date = LocalDate.of(2024, 1, 15), payee = "Grocery Store")
        xact.addPost(Post(account = expenses, amount = Amount.of(BigDecimal("42.50"), usd)))
        xact.addPost(Post(account = checking)) // null amount
        xact.finalize()

        val inferred = xact.posts[1].amount
        assertNotNull(inferred)
        assertEquals(Amount.of(BigDecimal("-42.50"), usd), inferred)
    }

    @Test
    fun `Unbalanced transaction throws`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val root = Account()
        val expenses = root.findAccount("Expenses:Food")!!
        val checking = root.findAccount("Assets:Checking")!!

        val xact = Xact(date = LocalDate.of(2024, 1, 15), payee = "Bad Transaction")
        xact.addPost(Post(account = expenses, amount = Amount.of(BigDecimal("42.50"), usd)))
        xact.addPost(Post(account = checking, amount = Amount.of(BigDecimal("-10.00"), usd)))

        assertFailsWith<BalanceError> {
            xact.finalize()
        }
    }

    @Test
    fun `Multi-commodity implicit exchange`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val eur = CommodityPool.findOrCreate("EUR")
        val root = Account()
        val assets = root.findAccount("Assets:USD")!!
        val assetsEur = root.findAccount("Assets:EUR")!!

        val xact = Xact(date = LocalDate.of(2024, 1, 15), payee = "Currency Exchange")
        xact.addPost(Post(account = assets, amount = Amount.of(BigDecimal("-100.00"), usd)))
        xact.addPost(Post(account = assetsEur, amount = Amount.of(BigDecimal("85.00"), eur)))

        // Multi-commodity with all explicit amounts => implicit exchange, should not throw
        xact.finalize()
    }

    @Test
    fun `Virtual postings are not balance-checked`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val root = Account()
        val expenses = root.findAccount("Expenses:Food")!!
        val checking = root.findAccount("Assets:Checking")!!
        val budget = root.findAccount("Budget:Food")!!

        val xact = Xact(date = LocalDate.of(2024, 1, 15), payee = "Grocery Store")
        xact.addPost(Post(account = expenses, amount = Amount.of(BigDecimal("42.50"), usd)))
        xact.addPost(Post(account = checking, amount = Amount.of(BigDecimal("-42.50"), usd)))
        // Virtual posting -- does not need to balance
        xact.addPost(Post(
            account = budget,
            amount = Amount.of(BigDecimal("-42.50"), usd),
            isVirtual = true
        ))

        xact.finalize() // Should not throw
    }

    @Test
    fun `Balanced virtual postings must balance among themselves`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val root = Account()
        val expenses = root.findAccount("Expenses:Food")!!
        val checking = root.findAccount("Assets:Checking")!!
        val budgetA = root.findAccount("Budget:Food")!!
        val budgetB = root.findAccount("Budget:Remaining")!!

        val xact = Xact(date = LocalDate.of(2024, 1, 15), payee = "Grocery Store")
        // Real postings balance
        xact.addPost(Post(account = expenses, amount = Amount.of(BigDecimal("42.50"), usd)))
        xact.addPost(Post(account = checking, amount = Amount.of(BigDecimal("-42.50"), usd)))
        // Balanced virtual postings balance among themselves
        xact.addPost(Post(
            account = budgetA,
            amount = Amount.of(BigDecimal("-42.50"), usd),
            isVirtual = true,
            isBalanceVirtual = true
        ))
        xact.addPost(Post(
            account = budgetB,
            amount = Amount.of(BigDecimal("42.50"), usd),
            isVirtual = true,
            isBalanceVirtual = true
        ))

        xact.finalize() // Should not throw
    }

    @Test
    fun `Unbalanced balanced-virtual postings throw`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val root = Account()
        val expenses = root.findAccount("Expenses:Food")!!
        val checking = root.findAccount("Assets:Checking")!!
        val budget = root.findAccount("Budget:Food")!!

        val xact = Xact(date = LocalDate.of(2024, 1, 15), payee = "Bad Budget")
        xact.addPost(Post(account = expenses, amount = Amount.of(BigDecimal("42.50"), usd)))
        xact.addPost(Post(account = checking, amount = Amount.of(BigDecimal("-42.50"), usd)))
        xact.addPost(Post(
            account = budget,
            amount = Amount.of(BigDecimal("-42.50"), usd),
            isVirtual = true,
            isBalanceVirtual = true
        ))

        assertFailsWith<BalanceError> {
            xact.finalize()
        }
    }

    @Test
    fun `Multiple null amounts in same group throw`() {
        CommodityPool.reset()
        val root = Account()
        val a = root.findAccount("A")!!
        val b = root.findAccount("B")!!
        val c = root.findAccount("C")!!

        val xact = Xact(payee = "Bad")
        xact.addPost(Post(account = a)) // null
        xact.addPost(Post(account = b)) // null
        xact.addPost(Post(account = c, amount = Amount.of(100)))

        assertFailsWith<BalanceError> {
            xact.finalize()
        }
    }

    @Test
    fun `Lot price derives cost`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val aapl = CommodityPool.findOrCreate("AAPL")
        val root = Account()
        val brokerage = root.findAccount("Assets:Brokerage")!!
        val checking = root.findAccount("Assets:Checking")!!

        val xact = Xact(date = LocalDate.of(2024, 1, 15), payee = "Buy Stock")
        val buyPost = Post(
            account = brokerage,
            amount = Amount.of(BigDecimal("10"), aapl),
            lotPrice = Amount.of(BigDecimal("150.00"), usd)
        )
        xact.addPost(buyPost)
        xact.addPost(Post(account = checking)) // null amount, inferred

        xact.finalize()

        // Cost should be derived: |10| * $150.00 = $1500.00
        assertNotNull(buyPost.cost)
        assertEquals(Amount.of(BigDecimal("1500.00"), usd), buyPost.cost)
        // Checking should be inferred as -$1500.00
        assertEquals(Amount.of(BigDecimal("-1500.00"), usd), xact.posts[1].amount)
    }

    // ---- Journal tests ------------------------------------------------------

    @Test
    fun `Journal addTransaction finalizes and stores`() {
        CommodityPool.reset()
        val usd = CommodityPool.findOrCreate("$")
        val journal = Journal()
        val expenses = journal.findOrCreateAccount("Expenses:Food")
        val checking = journal.findOrCreateAccount("Assets:Checking")

        val xact = Xact(date = LocalDate.of(2024, 1, 15), payee = "Grocery")
        xact.addPost(Post(account = expenses, amount = Amount.of(BigDecimal("42.50"), usd)))
        xact.addPost(Post(account = checking, amount = Amount.of(BigDecimal("-42.50"), usd)))

        journal.addTransaction(xact)
        assertEquals(1, journal.size)
    }

    @Test
    fun `Journal findOrCreateAccount creates hierarchy`() {
        CommodityPool.reset()
        val journal = Journal()
        val account = journal.findOrCreateAccount("Expenses:Food:Dining")
        assertEquals("Expenses:Food:Dining", account.fullname)
        // Parent accounts should also exist
        assertNotNull(journal.root.findAccount("Expenses", autoCreate = false))
        assertNotNull(journal.root.findAccount("Expenses:Food", autoCreate = false))
    }

    @Test
    fun `Journal alias resolution`() {
        CommodityPool.reset()
        val journal = Journal()
        journal.aliases["food"] = "Expenses:Food:Dining"
        val account = journal.findOrCreateAccount("food")
        assertEquals("Expenses:Food:Dining", account.fullname)
    }

    // ---- Item tests ---------------------------------------------------------

    @Test
    fun `Item state and tags`() {
        val item = Item()
        assertEquals(TransactionState.UNCLEARED, item.state)
        item.state = TransactionState.CLEARED
        assertEquals(TransactionState.CLEARED, item.state)

        assertFalse(item.hasTag("Payee"))
        item.setTag("Payee", "Store")
        assertTrue(item.hasTag("Payee"))
        assertEquals("Store", item.getTag("Payee"))
    }

    @Test
    fun `Post mustBalance`() {
        val root = Account()
        val a = root.findAccount("A")!!

        // Real posting must balance
        val realPost = Post(account = a)
        assertTrue(realPost.mustBalance())

        // Virtual posting does NOT need to balance
        val virtualPost = Post(account = a, isVirtual = true)
        assertFalse(virtualPost.mustBalance())

        // Balanced-virtual posting MUST balance
        val balVirtualPost = Post(account = a, isVirtual = true, isBalanceVirtual = true)
        assertTrue(balVirtualPost.mustBalance())
    }
}
