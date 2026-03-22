package muonledger

import java.io.File
import java.math.BigDecimal
import java.time.LocalDate
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ParserTest {

    @BeforeTest
    fun setUp() {
        CommodityPool.reset()
    }

    // ---- Basic 2-posting transaction ----------------------------------------

    @Test
    fun `basic two-posting transaction`() {
        val parser = Parser()
        val count = parser.parse("""
2024-01-15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
""".trimIndent())

        assertEquals(1, count)
        assertEquals(1, parser.journal.size)
        val xact = parser.journal.transactions[0]
        assertEquals(LocalDate.of(2024, 1, 15), xact.date)
        assertEquals("Grocery Store", xact.payee)
        assertEquals(2, xact.posts.size)

        val post0 = xact.posts[0]
        assertEquals("Expenses:Food", post0.account.fullname)
        assertNotNull(post0.amount)

        val post1 = xact.posts[1]
        assertEquals("Assets:Checking", post1.account.fullname)
        // Inferred amount
        assertNotNull(post1.amount)
    }

    // ---- State markers (* and !) --------------------------------------------

    @Test
    fun `cleared state marker`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 * Cleared transaction
    Expenses:Food              $50.00
    Assets:Checking
""".trimIndent())

        val xact = parser.journal.transactions[0]
        assertEquals(TransactionState.CLEARED, xact.state)
    }

    @Test
    fun `pending state marker`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 ! Pending payment
    Expenses:Food              $50.00
    Assets:Checking
""".trimIndent())

        val xact = parser.journal.transactions[0]
        assertEquals(TransactionState.PENDING, xact.state)
    }

    // ---- Null amount inference ----------------------------------------------

    @Test
    fun `null amount is inferred`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 Test
    Expenses:Food              $50.00
    Assets:Checking
""".trimIndent())

        val xact = parser.journal.transactions[0]
        val inferredPost = xact.posts[1]
        assertNotNull(inferredPost.amount)
        // Should be -$50.00
        assertTrue(inferredPost.amount!!.isNegative)
    }

    // ---- Virtual postings ---------------------------------------------------

    @Test
    fun `virtual posting with parentheses`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 Budget allocation
    (Budget:Savings)            $500.00
""".trimIndent())

        val xact = parser.journal.transactions[0]
        assertEquals(1, xact.posts.size)
        val post = xact.posts[0]
        assertTrue(post.isVirtual)
        assertFalse(post.isBalanceVirtual)
        assertEquals("Budget:Savings", post.account.fullname)
    }

    @Test
    fun `balanced virtual posting with brackets`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 Budget allocation
    [Budget:Emergency]          $200.00
    [Budget:Offset]            -$200.00
""".trimIndent())

        val xact = parser.journal.transactions[0]
        assertEquals(2, xact.posts.size)
        val post = xact.posts[0]
        assertTrue(post.isVirtual)
        assertTrue(post.isBalanceVirtual)
        assertEquals("Budget:Emergency", post.account.fullname)
    }

    // ---- Cost @ and @@ ------------------------------------------------------

    @Test
    fun `per-unit cost with at sign`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 Currency exchange
    Assets:Euro                100 EUR @ $1.10
    Assets:Checking
""".trimIndent())

        val xact = parser.journal.transactions[0]
        val post = xact.posts[0]
        assertNotNull(post.amount)
        assertNotNull(post.cost)
        // cost = 100 * $1.10 = $110.00
        assertEquals(0, post.cost!!.quantity!!.compareTo(BigDecimal("110.00")))
    }

    @Test
    fun `total cost with double at sign`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 Currency exchange
    Assets:Euro                100 EUR @@ $110.00
    Assets:Checking
""".trimIndent())

        val xact = parser.journal.transactions[0]
        val post = xact.posts[0]
        assertNotNull(post.cost)
        // total cost = $110.00
        assertEquals(0, post.cost!!.quantity!!.compareTo(BigDecimal("110.00")))
    }

    // ---- Lot annotation {$price} --------------------------------------------

    @Test
    fun `lot annotation derives cost`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 Buy stock
    Assets:Brokerage           10 AAPL {$150.00}
    Assets:Checking
""".trimIndent())

        val xact = parser.journal.transactions[0]
        val post = xact.posts[0]
        assertNotNull(post.amount)
        assertNotNull(post.lotPrice)
        // cost derived from lot: 10 * $150 = $1500.00
        assertNotNull(post.cost)
        assertEquals(0, post.cost!!.quantity!!.compareTo(BigDecimal("1500.00")))
    }

    // ---- Balance assertion = amount -----------------------------------------

    @Test
    fun `balance assertion`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 Deposit
    Assets:Checking             $1000.00
    Income:Salary

2024-01-16 Groceries
    Expenses:Food              $50.00
    Assets:Checking             = $950.00
""".trimIndent())

        assertEquals(2, parser.journal.size)
        val xact = parser.journal.transactions[1]
        val post = xact.posts[1]
        assertNotNull(post.assignedAmount)
        assertEquals(0, post.assignedAmount!!.quantity!!.compareTo(BigDecimal("950.00")))
    }

    // ---- Alias directive ----------------------------------------------------

    @Test
    fun `alias directive`() {
        val parser = Parser()
        parser.parse("""
alias chk=Assets:Checking

2024-01-15 Test
    Expenses:Food              $50.00
    chk
""".trimIndent())

        assertEquals(1, parser.journal.size)
        val xact = parser.journal.transactions[0]
        assertEquals("Assets:Checking", xact.posts[1].account.fullname)
    }

    // ---- Apply account directive --------------------------------------------

    @Test
    fun `apply account directive`() {
        val parser = Parser()
        parser.parse("""
apply account Assets

2024-01-15 Test
    Checking                   $50.00
    Savings                   -$50.00

end apply account

2024-01-16 Test2
    Expenses:Food              $25.00
    Assets:Checking
""".trimIndent())

        assertEquals(2, parser.journal.size)
        val xact0 = parser.journal.transactions[0]
        assertEquals("Assets:Checking", xact0.posts[0].account.fullname)
        assertEquals("Assets:Savings", xact0.posts[1].account.fullname)

        // After end apply account, no prefix
        val xact1 = parser.journal.transactions[1]
        assertEquals("Expenses:Food", xact1.posts[0].account.fullname)
    }

    // ---- Comment block ------------------------------------------------------

    @Test
    fun `comment block is skipped`() {
        val parser = Parser()
        val count = parser.parse("""
comment
This entire block should be ignored.
2024-01-01 Not a real transaction
end comment

2024-01-15 Real transaction
    Expenses:Food              $50.00
    Assets:Checking
""".trimIndent())

        assertEquals(1, count)
        assertEquals(1, parser.journal.size)
    }

    // ---- Include directive --------------------------------------------------

    @Test
    fun `include directive`() {
        // Create a temporary file to include
        val tempDir = File(System.getProperty("java.io.tmpdir"))
        val includeFile = File(tempDir, "test_include_${System.nanoTime()}.dat")
        try {
            includeFile.writeText("""
2024-02-01 Included Transaction
    Expenses:Rent              $1000.00
    Assets:Checking
""".trimIndent())

            val mainFile = File(tempDir, "test_main_${System.nanoTime()}.dat")
            mainFile.writeText("""
2024-01-15 Main Transaction
    Expenses:Food              $50.00
    Assets:Checking

include ${includeFile.name}
""".trimIndent())

            try {
                val parser = Parser()
                parser.parse(mainFile)
                // Included file adds its transaction to the same journal
                assertEquals(2, parser.journal.size)
            } finally {
                mainFile.delete()
            }
        } finally {
            includeFile.delete()
        }
    }

    // ---- Price directive P --------------------------------------------------

    @Test
    fun `price directive`() {
        val parser = Parser()
        parser.parse("""
P 2024-01-15 EUR $1.10

2024-01-15 Test
    Expenses:Food              $50.00
    Assets:Checking
""".trimIndent())

        assertEquals(1, parser.prices.size)
        val (date, commodity, price) = parser.prices[0]
        assertEquals(LocalDate.of(2024, 1, 15), date)
        assertEquals("EUR", commodity)
        assertEquals(0, price.quantity!!.compareTo(BigDecimal("1.10")))
    }

    // ---- Automated transaction = --------------------------------------------

    @Test
    fun `automated transaction`() {
        val parser = Parser()
        parser.parse("""
= Expenses:Food
    (Budget:Food)               1.0

2024-01-15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
""".trimIndent())

        assertEquals(1, parser.autoXacts.size)
        assertEquals("Expenses:Food", parser.autoXacts[0].predicate)
        assertEquals(1, parser.autoXacts[0].posts.size)
    }

    // ---- Periodic transaction ~ ---------------------------------------------

    @Test
    fun `periodic transaction`() {
        val parser = Parser()
        parser.parse("""
~ Monthly
    Expenses:Rent              $1000.00
    Assets:Checking

2024-01-15 Grocery Store
    Expenses:Food              $50.00
    Assets:Checking
""".trimIndent())

        assertEquals(1, parser.periodicXacts.size)
        assertEquals("Monthly", parser.periodicXacts[0].period)
        assertEquals(2, parser.periodicXacts[0].posts.size)
    }

    // ---- Payee with | note --------------------------------------------------

    @Test
    fun `payee with pipe note`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 Store | Receipt #123
    Expenses:Food              $50.00
    Assets:Checking
""".trimIndent())

        val xact = parser.journal.transactions[0]
        assertEquals("Store", xact.payee)
        assertNotNull(xact.note)
        assertTrue(xact.note!!.contains("Receipt #123"))
    }

    // ---- Date with / separator ----------------------------------------------

    @Test
    fun `date with slash separator`() {
        val parser = Parser()
        parser.parse("""
2024/01/15 Test
    Expenses:Food              $50.00
    Assets:Checking
""".trimIndent())

        val xact = parser.journal.transactions[0]
        assertEquals(LocalDate.of(2024, 1, 15), xact.date)
    }

    // ---- Comma thousands separator ------------------------------------------

    @Test
    fun `comma thousands separator`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 Big purchase
    Expenses:Equipment         $12,500.00
    Assets:Checking
""".trimIndent())

        val xact = parser.journal.transactions[0]
        val post = xact.posts[0]
        assertNotNull(post.amount)
        assertEquals(0, post.amount!!.quantity!!.compareTo(BigDecimal("12500.00")))
    }

    // ---- Inline comment on posting ------------------------------------------

    @Test
    fun `inline comment on posting`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 Test
    Expenses:Food              $25.00  ; lunch
    Assets:Checking
""".trimIndent())

        val xact = parser.journal.transactions[0]
        val post = xact.posts[0]
        assertEquals("lunch", post.note)
    }

    // ---- Multiple transactions ----------------------------------------------

    @Test
    fun `multiple transactions`() {
        val parser = Parser()
        val count = parser.parse("""
2024-01-15 First
    Expenses:Food              $50.00
    Assets:Checking

2024-01-16 Second
    Expenses:Rent              $1000.00
    Assets:Checking
""".trimIndent())

        assertEquals(2, count)
        assertEquals(2, parser.journal.size)
        assertEquals("First", parser.journal.transactions[0].payee)
        assertEquals("Second", parser.journal.transactions[1].payee)
    }

    // ---- Line comments are skipped ------------------------------------------

    @Test
    fun `line comments are skipped`() {
        val parser = Parser()
        val count = parser.parse("""
; This is a comment
# This is also a comment

2024-01-15 Test
    Expenses:Food              $50.00
    Assets:Checking
""".trimIndent())

        assertEquals(1, count)
    }

    // ---- Suffix commodity ---------------------------------------------------

    @Test
    fun `suffix commodity`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 Test
    Assets:Euro                100 EUR
    Assets:Checking           -100 EUR
""".trimIndent())

        val post = parser.journal.transactions[0].posts[0]
        assertNotNull(post.amount)
        assertEquals("EUR", post.amount!!.commodity?.symbol)
        assertEquals(0, post.amount!!.quantity!!.compareTo(BigDecimal("100")))
    }

    // ---- Negative prefix amount ---------------------------------------------

    @Test
    fun `negative prefix amount`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 Test
    Assets:Checking            $-15.00
    Expenses:Refund             $15.00
""".trimIndent())

        val post = parser.journal.transactions[0].posts[0]
        assertNotNull(post.amount)
        assertTrue(post.amount!!.isNegative)
        assertEquals(0, post.amount!!.quantity!!.compareTo(BigDecimal("-15.00")))
    }

    // ---- Balance assertion only (no amount) ---------------------------------

    @Test
    fun `balance assertion with no amount`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 Deposit
    Assets:Checking             $1000.00
    Income:Salary

2024-01-16 Check
    Assets:Checking              = $1000.00
    Equity:Adjustments           $0.00
""".trimIndent())

        assertEquals(2, parser.journal.size)
        val xact = parser.journal.transactions[1]
        val post = xact.posts[0]
        // No explicit amount, just assertion — amount was inferred by finalize
        assertNotNull(post.assignedAmount)
        assertEquals(0, post.assignedAmount!!.quantity!!.compareTo(BigDecimal("1000.00")))
    }

    // ---- Transaction note on next line (comment) ----------------------------

    @Test
    fun `transaction note from indented comment`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 Test
    ; This is a transaction note
    Expenses:Food              $50.00
    Assets:Checking
""".trimIndent())

        val xact = parser.journal.transactions[0]
        assertNotNull(xact.note)
        assertTrue(xact.note!!.contains("This is a transaction note"))
    }

    // ---- Posting note from following comment line ---------------------------

    @Test
    fun `posting note from following comment line`() {
        val parser = Parser()
        parser.parse("""
2024-01-15 Test
    Expenses:Food              $50.00
    ; This is a posting note
    Assets:Checking
""".trimIndent())

        val xact = parser.journal.transactions[0]
        val post = xact.posts[0]
        assertNotNull(post.note)
        assertTrue(post.note!!.contains("This is a posting note"))
    }
}
