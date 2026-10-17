package io.github.agcarbajo.galaxycompanion.dualboot

import org.junit.Assert.*
import org.junit.Test

class AppUpdateTest {
    private val hash = "a".repeat(64)

    private fun release(vararg assets: Pair<String, Long>) = """{"tag_name": "v2.4.0",
        "html_url": "https://github.com/agcarbajo/galaxy-companion/releases/tag/v2.4.0",
        "assets": [${assets.joinToString(",") { (name, size) ->
            """{"name": "$name", "size": $size,
                "browser_download_url": "https://github.com/agcarbajo/galaxy-companion/releases/download/v2.4.0/$name"}"""
        }}]}"""

    @Test fun findsTheApkNextToTheLinuxPackage() {
        val r = AppUpdate.parseRelease(release("galaxy-companion_2.4.0_all.deb" to 900,
            "galaxy-companion-dualboot_2.4.0.apk" to 1000, "SHA256SUMS" to 200))!!
        assertEquals("2.4.0", r.version)
        assertEquals("galaxy-companion-dualboot_2.4.0.apk", r.apkName)
        assertEquals(1000L, r.apkSize)
        assertTrue(r.sumsUrl.endsWith("/SHA256SUMS"))
    }

    @Test fun aReleaseWithoutApkOrSumsOffersNothing() {
        assertNull(AppUpdate.parseRelease(release("galaxy-companion_2.4.0_all.deb" to 900, "SHA256SUMS" to 200)))
        assertNull(AppUpdate.parseRelease(release("galaxy-companion-dualboot_2.4.0.apk" to 1000)))
        assertNull(AppUpdate.parseRelease(release("galaxy-companion-dualboot_2.4.0.apk" to AppUpdate.MAX_APK + 1,
            "SHA256SUMS" to 200)))
        assertNull(AppUpdate.parseRelease(release("../galaxy-companion-dualboot_2.4.0.apk" to 1, "SHA256SUMS" to 2)))
    }

    @Test fun sumsAreReadByExactName() {
        val sums = "$hash  galaxy-companion_2.4.0_all.deb\n${"b".repeat(64)} *galaxy-companion-dualboot_2.4.0.apk\n"
        assertEquals("b".repeat(64), AppUpdate.parseSums(sums, "galaxy-companion-dualboot_2.4.0.apk"))
        assertNull(AppUpdate.parseSums(sums, "galaxy-companion-dualboot_2.4.1.apk"))
        assertNull(AppUpdate.parseSums("XYZ  galaxy-companion-dualboot_2.4.0.apk", "galaxy-companion-dualboot_2.4.0.apk"))
    }

    @Test fun versionsCompareAsNumbers() {
        assertEquals(100900, AppUpdate.code("0.9.0"))
        assertEquals(110000, AppUpdate.code("1.0.0"))
        assertTrue(AppUpdate.newer("1.0.0", AppUpdate.code("0.9.0")))
        assertTrue(AppUpdate.newer("0.9.0", 20300))  // the last build before the restart
        assertFalse(AppUpdate.newer("0.9.0", AppUpdate.code("0.9.0")))
        assertFalse(AppUpdate.newer("0.8.9", AppUpdate.code("0.9.0")))
    }
}
