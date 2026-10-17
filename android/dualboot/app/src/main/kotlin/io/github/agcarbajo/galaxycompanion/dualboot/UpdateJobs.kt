package io.github.agcarbajo.galaxycompanion.dualboot

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.app.Notification
import android.os.Build
import java.util.concurrent.Executors

/** The weekly check: a persisted job that needs a network, and a notification. */
object UpdateSchedule {
    private const val JOB_ID = 120
    private const val WEEK_MS = 7L * 24 * 60 * 60 * 1000
    private const val CHANNEL = "updates"

    /** Schedules or cancels the weekly check to match the setting. */
    fun apply(context: Context) {
        val scheduler = context.getSystemService(JobScheduler::class.java)
        if (!Prefs(context).weeklyUpdateCheck) {
            scheduler.cancel(JOB_ID)
            return
        }
        if (scheduler.getPendingJob(JOB_ID) != null) return
        scheduler.schedule(
            JobInfo.Builder(JOB_ID, ComponentName(context, UpdateCheckJob::class.java))
                .setPeriodic(WEEK_MS)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPersisted(true)
                .build()
        )
    }

    fun notify(context: Context, title: String, body: String) {
        // Before Android 13 notifications need no permission.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED) return
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(
            CHANNEL, context.getString(R.string.notify_channel), NotificationManager.IMPORTANCE_DEFAULT))
        val open = PendingIntent.getActivity(context, 0, Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE)
        manager.notify(1, Notification.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_tile_dualboot)
            .setContentTitle(title)
            .setContentText(body)
            .setContentIntent(open)
            .setAutoCancel(true)
            .build())
    }
}

/** Checks for a newer release and says so once per version. */
class UpdateCheckJob : JobService() {
    private val executor = Executors.newSingleThreadExecutor()

    override fun onStartJob(params: JobParameters): Boolean {
        executor.execute {
            try {
                val release = AppUpdate.check()
                val prefs = Prefs(this)
                if (release != null && prefs.notifiedVersion != release.version) {
                    UpdateSchedule.notify(this, getString(R.string.notify_title, release.version),
                        getString(R.string.notify_body))
                    prefs.notifiedVersion = release.version
                }
            } catch (e: Exception) {
                // Offline, or nothing published: the next week tries again.
            } finally {
                jobFinished(params, false)
            }
        }
        return true
    }

    override fun onStopJob(params: JobParameters) = true

    override fun onDestroy() {
        executor.shutdown()
        super.onDestroy()
    }
}

/** What Android did with an update handed to it by [AppUpdate.install]. */
class InstallReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                @Suppress("DEPRECATION")
                val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT) ?: return
                context.startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }
            // On success Android restarts nothing: the app is simply replaced,
            // and MY_PACKAGE_REPLACED runs the usual boot check.
            PackageInstaller.STATUS_SUCCESS -> Prefs(context).updateError = null
            else -> {
                val detail = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE).orEmpty()
                Prefs(context).updateError = detail.ifEmpty { "status ${intent.getIntExtra(PackageInstaller.EXTRA_STATUS, -1)}" }
                UpdateSchedule.notify(context, context.getString(R.string.update_failed),
                    context.getString(R.string.update_error_install))
            }
        }
    }
}
