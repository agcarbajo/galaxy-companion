package io.github.agcarbajo.galaxycompanion.dualboot

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class ProfileTest {
    private val dir = File(System.getProperty("profiles.dir")!!)
    private fun shipped(id: String) = Profile.parse(File(dir, "$id.json").readText())

    @Test fun tabProfileFromTheRepository() {
        val tab = shipped("gts9uwifi")!!
        assertEquals(listOf("boot", "init_boot", "vendor_boot", "dtbo"), tab.partitions.map { it.name })
        assertEquals(8_388_608L, tab.partitions[1].size)
        assertEquals("boot", tab.kernelPartition)
        assertEquals("linuxroot", tab.linuxRoot)
        assertEquals("/var/lib/gts9u-boot-sets", tab.setsDir)
        assertEquals("/var/lib/gts9u-boot-backups", tab.backupsDir)
        assertEquals(tab, Profile.match(listOf(tab), listOf("gts9uwifi", "gts9uwifixx")))
    }

    @Test fun profilesWithoutDualBootAreSkipped() {
        assertNull(shipped("star2lte"))
        // Every shipped profile with dual boot must parse: the app is built from them.
        dir.listFiles { f -> f.name.endsWith(".json") }!!.forEach { file ->
            if ("\"dual-boot\"" in file.readText()) assertNotNull(file.name, Profile.parse(file.readText()))
        }
    }

    @Test fun aSingleBootPartitionByNameIsEnough() {
        val p = Profile.parse("""{"id": "x", "features": ["dual-boot"], "dual_boot":
            {"partitions": ["boot"], "linux_root": "userdata_linux", "android_devices": ["x1"]}}""")!!
        assertEquals(listOf(Profile.Part("boot", 0)), p.partitions)
        assertEquals("ext4", p.linuxRootFs)
        assertEquals("/var/lib/galaxy-companion/boot-sets", p.setsDir)
        assertEquals("/var/lib/galaxy-companion/boot-sets-backups", p.backupsDir)
        assertNull(Profile.match(listOf(p), listOf("x2")))
    }

    @Test fun namesThatCouldBreakAShellLineAreRefused() {
        assertNull(Profile.parse("""{"features": ["dual-boot"], "dual_boot":
            {"partitions": ["boot"], "linux_root": "linux; rm -rf /"}}"""))
        assertNull(Profile.parse("""{"features": ["dual-boot"], "dual_boot":
            {"partitions": ["boot"], "linux_root": "linuxroot", "sets_dir": "/var/lib/a b"}}"""))
    }
}
