package io.github.agcarbajo.galaxycompanion.dualboot

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.*
import org.junit.Test

class KernelCheckTest {
    private fun header(version: Int, kernelSize: Int, page: Int): ByteArray {
        val b = ByteBuffer.allocate(4096).order(ByteOrder.LITTLE_ENDIAN)
        b.put("ANDROID!".toByteArray())
        b.putInt(8, kernelSize)
        if (version < 3) b.putInt(36, page) else b.putInt(20, 0x1234)  // v3 keeps os_version near there
        b.putInt(40, version)
        return b.array()
    }

    @Test fun headerVersionsZeroToTwoUseTheirPageSize() {
        assertEquals(KernelCheck.Kernel(2048, 1000), KernelCheck.locate(header(1, 1000, 2048)))
        assertEquals(KernelCheck.Kernel(4096, 5), KernelCheck.locate(header(2, 5, 4096)))
    }
    @Test fun headerVersionsThreeAndFourUseFourKiB() {
        assertEquals(KernelCheck.Kernel(4096, 77), KernelCheck.locate(header(4, 77, 0)))
    }
    @Test fun notABootImage() {
        assertNull(KernelCheck.locate(ByteArray(4096)))
        assertNull(KernelCheck.locate(header(1, 10, 1000)))  // not a power of two
    }
    @Test fun compressionIsRecognised() {
        assertEquals(KernelCheck.Compression.GZIP, KernelCheck.compression(byteArrayOf(0x1f, 0x8b.toByte(), 8)))
        assertEquals(KernelCheck.Compression.LZ4, KernelCheck.compression(byteArrayOf(0x02, 0x21, 0x4c, 0x18)))
        assertEquals(KernelCheck.Compression.LZ4, KernelCheck.compression(byteArrayOf(0x04, 0x22, 0x4d, 0x18)))
        assertEquals(KernelCheck.Compression.RAW, KernelCheck.compression("MZ\u0000\u0000".toByteArray()))
    }
    @Test fun theNeedleEndsWithASpace() {
        // "6.1.1" must not match a kernel "6.1.10".
        assertEquals("Linux version 6.1.1 ", KernelCheck.needle("6.1.1"))
    }
}
