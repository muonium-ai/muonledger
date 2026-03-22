package muonledger

import java.math.BigDecimal
import kotlin.test.*

class AmountTest {

    @BeforeTest
    fun setup() {
        CommodityPool.reset()
    }

    // ---- Creation -----------------------------------------------------------

    @Test
    fun `create from BigDecimal with commodity`() {
        val usd = CommodityPool.findOrCreate("$")
        usd.precision = 2
        usd.dropFlags(CommodityStyle.SUFFIXED) // make it prefix
        val amt = Amount.of(BigDecimal("50.00"), usd)
        assertEquals(BigDecimal("50.00"), amt.quantity)
        assertEquals(usd, amt.commodity)
    }

    @Test
    fun `create from integer`() {
        val amt = Amount.of(100)
        assertEquals(BigDecimal(100), amt.quantity)
        assertNull(amt.commodity)
        assertFalse(amt.isZero)
    }

    @Test
    fun `nil amount is null`() {
        val amt = Amount.nil()
        assertTrue(amt.isNull)
    }

    // ---- Parsing ------------------------------------------------------------

    @Test
    fun `parse dollar amount`() {
        val amt = Amount.parse("$50.00")
        assertEquals(BigDecimal("50.00"), amt.quantity)
        assertEquals("$", amt.commodity?.symbol)
        assertTrue(amt.commodity?.isPrefix == true)
    }

    @Test
    fun `parse suffix commodity`() {
        val amt = Amount.parse("100 EUR")
        assertEquals(BigDecimal("100"), amt.quantity)
        assertEquals("EUR", amt.commodity?.symbol)
        assertFalse(amt.commodity?.isPrefix == true)
    }

    @Test
    fun `parse negative dollar amount`() {
        val amt = Amount.parse("$-15.00")
        // Leading sign variant
        val amt2 = Amount.parse("-$15.00")
        assertEquals(BigDecimal("-15.00"), amt2.quantity)
    }

    @Test
    fun `parse thousands separator`() {
        val amt = Amount.parse("$12,500.00")
        assertEquals(0, BigDecimal("12500.00").compareTo(amt.quantity))
    }

    // ---- Addition -----------------------------------------------------------

    @Test
    fun `add two amounts`() {
        val a = Amount.parse("$10.00")
        val b = Amount.parse("$20.00")
        val sum = a + b
        assertEquals(0, BigDecimal("30.00").compareTo(sum.quantity))
        assertEquals("$", sum.commodity?.symbol)
    }

    @Test
    fun `add amounts with different commodities throws`() {
        val a = Amount.parse("$10.00")
        val b = Amount.parse("100 EUR")
        assertFailsWith<IllegalArgumentException> { a + b }
    }

    // ---- Subtraction --------------------------------------------------------

    @Test
    fun `subtract two amounts`() {
        val a = Amount.parse("$30.00")
        val b = Amount.parse("$10.00")
        val diff = a - b
        assertEquals(0, BigDecimal("20.00").compareTo(diff.quantity))
    }

    // ---- Negation -----------------------------------------------------------

    @Test
    fun `negate amount`() {
        val a = Amount.parse("$50.00")
        val neg = -a
        assertEquals(0, BigDecimal("-50.00").compareTo(neg.quantity))
        assertEquals("$", neg.commodity?.symbol)
    }

    @Test
    fun `negate negative amount`() {
        val a = Amount.parse("-$50.00")
        val pos = -a
        assertEquals(0, BigDecimal("50.00").compareTo(pos.quantity))
    }

    // ---- Abs ----------------------------------------------------------------

    @Test
    fun `abs of negative`() {
        val a = Amount.parse("-$50.00")
        val abs = a.abs()
        assertEquals(0, BigDecimal("50.00").compareTo(abs.quantity))
    }

    @Test
    fun `abs of positive`() {
        val a = Amount.parse("$50.00")
        val abs = a.abs()
        assertEquals(0, BigDecimal("50.00").compareTo(abs.quantity))
    }

    // ---- isZero -------------------------------------------------------------

    @Test
    fun `isZero for zero amount`() {
        val a = Amount.of(BigDecimal.ZERO)
        assertTrue(a.isZero)
    }

    @Test
    fun `isZero for non-zero amount`() {
        val a = Amount.parse("$50.00")
        assertFalse(a.isZero)
    }

    // ---- Formatting ---------------------------------------------------------

    @Test
    fun `format prefix commodity`() {
        val amt = Amount.parse("$50.00")
        assertEquals("$50.00", amt.toString())
    }

    @Test
    fun `format suffix commodity`() {
        val amt = Amount.parse("100 EUR")
        assertEquals("100 EUR", amt.toString())
    }

    @Test
    fun `format negative prefix`() {
        val amt = Amount.parse("-$15.00")
        assertEquals("$-15.00", amt.toString())
    }

    @Test
    fun `format with thousands separator`() {
        val amt = Amount.parse("$12,500.00")
        assertEquals("$12,500.00", amt.toString())
    }

    @Test
    fun `format no commodity`() {
        val amt = Amount.of(BigDecimal("42.50"))
        assertEquals("42.50", amt.toString())
    }

    // ---- Comparison ---------------------------------------------------------

    @Test
    fun `compareTo amounts`() {
        val a = Amount.parse("$10.00")
        val b = Amount.parse("$20.00")
        assertTrue(a < b)
        assertTrue(b > a)
        assertFalse(a == b)
    }

    @Test
    fun `equality of equal amounts`() {
        val a = Amount.parse("$10.00")
        val b = Amount.parse("$10.00")
        assertEquals(a, b)
    }

    // ---- Multiply -----------------------------------------------------------

    @Test
    fun `multiply by scalar`() {
        val a = Amount.parse("$10.00")
        val result = a * BigDecimal("3")
        assertEquals(0, BigDecimal("30.00").compareTo(result.quantity))
    }
}
