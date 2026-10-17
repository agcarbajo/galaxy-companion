package io.github.agcarbajo.galaxycompanion.dualboot

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Base64

/**
 * Proves that the kernel on the boot partition is the Android kernel running
 * right now, before those partitions are saved as Android's.
 *
 * Without it, images left behind by an interrupted switch, or Linux's
 * images staged by hand, could be saved as "Android" and Android's own copy
 * lost.  Magisk's magiskboot unpacks and decompresses every format; without
 * it the Android boot image header is read here and the kernel searched
 * either as it is or through gzip.  An lz4 kernel without magiskboot cannot
 * be checked, and is then not saved.
 */
object KernelCheck {

    data class Kernel(val offset: Long, val size: Long)

    enum class Compression { RAW, GZIP, LZ4, UNKNOWN }

    data class Result(val ok: Boolean, val detail: String)

    private val MAGISKBOOT = listOf(
        "/data/adb/magisk/magiskboot",
        "/data/adb/ksu/bin/magiskboot",
        "/data/adb/ap/bin/magiskboot",
    )

    /**
     * Where the kernel is inside an Android boot image, from its header.
     *
     * Versions 0-2 keep the page size at offset 36; 3 and 4 fix it at 4096.
     * The kernel always starts on the first page after the header.
     */
    fun locate(header: ByteArray): Kernel? {
        if (header.size < 44 || String(header, 0, 8, Charsets.US_ASCII) != "ANDROID!") return null
        val buffer = ByteBuffer.wrap(header).order(ByteOrder.LITTLE_ENDIAN)
        val size = buffer.getInt(8).toLong() and 0xffffffffL
        val version = buffer.getInt(40)
        val page = if (version >= 3) 4096L else buffer.getInt(36).toLong() and 0xffffffffL
        if (size <= 0 || page < 2048 || page > 65536 || page and (page - 1) != 0L) return null
        return Kernel(page, size)
    }

    fun compression(start: ByteArray): Compression = when {
        start.size >= 2 && start[0] == 0x1f.toByte() && start[1] == 0x8b.toByte() -> Compression.GZIP
        start.size >= 4 && start[0] == 0x02.toByte() && start[1] == 0x21.toByte() &&
            start[2] == 0x4c.toByte() && start[3] == 0x18.toByte() -> Compression.LZ4
        start.size >= 4 && start[0] == 0x04.toByte() && start[1] == 0x22.toByte() &&
            start[2] == 0x4d.toByte() && start[3] == 0x18.toByte() -> Compression.LZ4
        else -> Compression.RAW
    }

    /** The string every Linux kernel image carries, for this release. */
    fun needle(release: String) = "Linux version $release "

    private fun quote(value: String) = "'" + value.replace("'", "'\\''") + "'"

    private fun bytes(device: String, offset: Long, count: Int): ByteArray? {
        // dd with a block size of one page keeps toybox's dd on its fast path.
        val skip = offset / 4096
        val within = offset % 4096
        val r = Root.run("dd if=$device bs=4096 skip=$skip count=1 2>/dev/null | " +
            "tail -c +${within + 1} | head -c $count | base64")
        if (!r.ok) return null
        return try { Base64.getMimeDecoder().decode(r.output) } catch (e: IllegalArgumentException) { null }
    }

    /** Whether the kernel in [partition] is the running one ([release], `uname -r`). */
    fun verify(partition: String, release: String, scratch: String): Result {
        val device = "/dev/block/by-name/$partition"
        val needle = quote(needle(release))

        val magiskboot = Root.run(
            "for m in ${MAGISKBOOT.joinToString(" ")} \$(command -v magiskboot); do " +
                "[ -x \"\$m\" ] && { echo \"\$m\"; break; }; done; true"
        ).output.lineSequence().firstOrNull()?.trim().orEmpty()
        if (magiskboot.isNotEmpty()) {
            val r = Root.run(
                "rm -rf $scratch && mkdir -p $scratch && cd $scratch",
                "$magiskboot unpack $device >/dev/null 2>&1 || true",
                "if [ -f kernel ] && grep -aFq $needle kernel; then echo match; else echo other; fi",
                "cd / && rm -rf $scratch",
            )
            return if (r.output.lines().contains("match")) Result(true, "kernel $release (magiskboot)")
            else Result(false, "the kernel on $partition is not the running $release")
        }

        val kernel = bytes(device, 0, 4096)?.let { locate(it) }
            ?: return Result(false, "$partition is not an Android boot image")
        val kind = bytes(device, kernel.offset, 16)?.let { compression(it) } ?: Compression.UNKNOWN
        val extract = "dd if=$device bs=4096 skip=${kernel.offset / 4096} " +
            "count=${(kernel.size + 4095) / 4096} 2>/dev/null | head -c ${kernel.size}"
        val search = when (kind) {
            Compression.RAW -> "$extract | grep -aFq $needle"
            Compression.GZIP -> "$extract | zcat 2>/dev/null | grep -aFq $needle"
            else -> return Result(false, "the kernel on $partition is $kind-compressed; " +
                "install Magisk (magiskboot) so it can be checked")
        }
        val r = Root.run("if $search; then echo match; else echo other; fi")
        return if (r.output.lines().contains("match")) Result(true, "kernel $release ($kind)")
        else Result(false, "the kernel on $partition is not the running $release")
    }
}
