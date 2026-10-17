package io.github.agcarbajo.galaxycompanion.dualboot

import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

class BootSafetyTest {
    private val profile = Profile("t", "Test",
        listOf(Profile.Part("dtbo", 16), Profile.Part("boot", 64)), "boot", "linuxroot", "ext4",
        "/var/lib/galaxy-companion/boot-sets", "/var/lib/galaxy-companion/boot-sets-backups", listOf("t"))

    // Before the sets below are built from BootSets.PARTITIONS.
    init { BootSets.configure(profile) }

    @Before fun configure() = BootSets.configure(profile)

    private fun set(id: String, value: String, kind: String = BootSets.kindFromId(id)) =
        BootSets.BootSet(id, id, true,
            BootSets.PARTITIONS.associate { "/sets/$id/${it.name}.img" to value }, "/sets/$id", kind)
    private val android = set("android", "a".repeat(64))
    private val linux = set("ubuntu", "b".repeat(64))
    private val sets = listOf(android, linux)
    private fun live(set: BootSets.BootSet) = BootSets.PARTITIONS.associate {
        it.device to set.hashes.getValue(set.file(it))
    }

    @Test fun theKernelIsWrittenFirst() {
        assertEquals(listOf("boot", "dtbo"), BootSets.PARTITIONS.map { it.name })
    }
    @Test fun wrongLabelsNeverMakeAndroidRunLinux() {
        assertEquals("android", BootSets.runningAndroid(sets, "One UI 8")?.id)
        assertEquals("One UI 8", BootSets.runningAndroid(sets, "One UI 8")?.label)
    }
    @Test fun theKindFileWinsOverTheId() {
        val renamed = set("mine", "c".repeat(64), BootSets.LINUX)
        assertTrue(BootSets.isLinux(renamed))
        assertFalse(BootSets.isLinux(set("lineage", "d".repeat(64))))
    }
    @Test fun unchangedBackupNeedsNoCopy() {
        assertEquals(BootSets.BackupDecision.UNCHANGED, BootSets.backupDecision(sets, live(android)))
    }
    @Test fun firstRunAfterInstallingLinuxCreatesAndroidsSet() {
        val fresh = live(android).mapValues { "e".repeat(64) }
        assertEquals(BootSets.BackupDecision.CREATE, BootSets.backupDecision(listOf(linux), fresh))
        // Even before Linux has saved its own.
        assertEquals(BootSets.BackupDecision.CREATE, BootSets.backupDecision(emptyList(), fresh))
    }
    @Test fun linuxImagesAreNeverSavedAsAndroid() {
        assertEquals(BootSets.BackupDecision.AMBIGUOUS, BootSets.backupDecision(listOf(linux), live(linux)))
        for (part in BootSets.PARTITIONS) {
            val half = live(android).mapValues { "e".repeat(64) } + (part.device to linux.hashes.getValue(linux.file(part)))
            assertEquals(BootSets.BackupDecision.MIXED, BootSets.backupDecision(listOf(linux), half))
        }
    }
    @Test fun stagedLinuxMustNeverBecomeAndroidBackup() {
        assertEquals(BootSets.BackupDecision.LINUX_STAGED, BootSets.backupDecision(sets, live(linux)))
        assertEquals("android", BootSets.runningAndroid(sets, "One UI 8")?.id)
    }
    @Test fun interruptedSwitchIsRejectedForEveryPartition() {
        for (part in BootSets.PARTITIONS) {
            val mixed = live(android) + (part.device to linux.hashes.getValue(linux.file(part)))
            assertEquals(BootSets.BackupDecision.MIXED, BootSets.backupDecision(sets, mixed))
        }
    }
    @Test fun changedAndroidRequiresVerifiedCapture() {
        val updated = live(android) + (BootSets.PARTITIONS.first().device to "c".repeat(64))
        assertEquals(BootSets.BackupDecision.CHANGED, BootSets.backupDecision(sets, updated))
    }
    @Test fun incompleteReadAndMultipleAndroidSetsAreRejected() {
        assertEquals(BootSets.BackupDecision.AMBIGUOUS, BootSets.backupDecision(sets, emptyMap()))
        assertEquals(BootSets.BackupDecision.AMBIGUOUS,
            BootSets.backupDecision(sets + set("lineage", "c".repeat(64)), live(android)))
    }
}
