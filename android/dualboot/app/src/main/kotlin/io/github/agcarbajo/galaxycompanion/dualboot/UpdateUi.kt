package io.github.agcarbajo.galaxycompanion.dualboot

import android.Manifest
import android.app.Application
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

sealed interface UpdateState {
    data object Idle : UpdateState
    data object Checking : UpdateState
    data object Latest : UpdateState
    data class Available(val release: AppUpdate.Release) : UpdateState
    data class Downloading(val percent: Int) : UpdateState
    data object Installing : UpdateState
    data class Failed(val failure: AppUpdate.Failure, val detail: String) : UpdateState
}

class UpdateViewModel(app: Application) : AndroidViewModel(app) {
    private val _state = MutableStateFlow<UpdateState>(UpdateState.Idle)
    val state = _state.asStateFlow()

    init {
        // Android's answer to the last attempt arrives while the app is gone.
        Prefs(app).updateError?.let {
            _state.value = UpdateState.Failed(AppUpdate.Failure.INSTALL, it)
            Prefs(app).updateError = null
        }
    }

    private fun failed(e: Exception) = UpdateState.Failed(
        (e as? AppUpdate.UpdateException)?.failure ?: AppUpdate.Failure.NETWORK, e.message.orEmpty())

    fun check() = viewModelScope.launch {
        _state.value = UpdateState.Checking
        _state.value = withContext(Dispatchers.IO) {
            try {
                AppUpdate.check()?.let { UpdateState.Available(it) } ?: UpdateState.Latest
            } catch (e: Exception) {
                failed(e)
            }
        }
    }

    fun install(release: AppUpdate.Release) = viewModelScope.launch {
        val context = getApplication<Application>()
        _state.value = UpdateState.Downloading(0)
        val file: File = withContext(Dispatchers.IO) {
            try {
                AppUpdate.download(context, release) { percent ->
                    _state.update { UpdateState.Downloading(percent) }
                }
            } catch (e: Exception) {
                _state.value = failed(e)
                null
            }
        } ?: return@launch
        _state.value = UpdateState.Installing
        withContext(Dispatchers.IO) {
            try {
                AppUpdate.install(context, file)
            } catch (e: Exception) {
                _state.value = UpdateState.Failed(AppUpdate.Failure.INSTALL, e.message.orEmpty())
            }
        }
    }
}

private fun failureText(failure: AppUpdate.Failure) = when (failure) {
    AppUpdate.Failure.NETWORK -> R.string.update_error_network
    AppUpdate.Failure.NOT_FOUND -> R.string.update_error_not_found
    AppUpdate.Failure.CHECKSUM -> R.string.update_error_checksum
    AppUpdate.Failure.PACKAGE -> R.string.update_error_package
    AppUpdate.Failure.SIGNATURE -> R.string.update_error_signature
    AppUpdate.Failure.INSTALL -> R.string.update_error_install
}

/** Version, a check button, what it found, and the weekly check. */
@Composable
fun UpdateCard(vm: UpdateViewModel = viewModel()) {
    val state by vm.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val prefs = remember { Prefs(context) }
    var weekly by remember { mutableStateOf(prefs.weeklyUpdateCheck) }
    val askNotifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    // The weekly check is on by default, so its notification permission is
    // asked for once, the first time this card is shown.
    LaunchedEffect(Unit) {
        if (weekly && !prefs.askedNotifications && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            prefs.askedNotifications = true
            askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
    val busy = state is UpdateState.Checking || state is UpdateState.Downloading || state is UpdateState.Installing

    Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(24.dp)) {
        Column {
            Column(Modifier.padding(horizontal = 20.dp, vertical = 16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(stringResource(R.string.about_version, BuildConfig.VERSION_NAME),
                    style = MaterialTheme.typography.titleMedium)
                val line = when (val s = state) {
                    UpdateState.Idle -> null
                    UpdateState.Checking -> stringResource(R.string.update_checking)
                    UpdateState.Latest -> stringResource(R.string.update_none)
                    is UpdateState.Available -> stringResource(R.string.update_available, s.release.version)
                    is UpdateState.Downloading -> stringResource(R.string.update_downloading, s.percent)
                    UpdateState.Installing -> stringResource(R.string.update_installing)
                    is UpdateState.Failed -> stringResource(failureText(s.failure))
                }
                line?.let {
                    Text(it, style = MaterialTheme.typography.bodyMedium,
                        color = if (state is UpdateState.Failed) MaterialTheme.colorScheme.error
                        else MaterialTheme.colorScheme.onSurfaceVariant)
                }
                (state as? UpdateState.Failed)?.detail?.takeIf { it.isNotBlank() }?.let {
                    Text(it, style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                (state as? UpdateState.Downloading)?.let { s ->
                    LinearProgressIndicator(progress = { s.percent / 100f }, modifier = Modifier.fillMaxWidth())
                }
                Spacer(Modifier.height(4.dp))
                when (val s = state) {
                    is UpdateState.Available -> Button(
                        onClick = { vm.install(s.release) },
                        shape = RoundedCornerShape(16.dp),
                    ) { Text(stringResource(R.string.update_install)) }
                    else -> TextButton(onClick = { vm.check() }, enabled = !busy) {
                        Text(stringResource(R.string.update_check))
                    }
                }
            }
            HorizontalDivider(Modifier.padding(horizontal = 20.dp))
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(stringResource(R.string.update_weekly_title), style = MaterialTheme.typography.titleMedium)
                    Text(stringResource(R.string.update_weekly_body), style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Spacer(Modifier.width(12.dp))
                Switch(checked = weekly, onCheckedChange = {
                    weekly = it
                    prefs.weeklyUpdateCheck = it
                    UpdateSchedule.apply(context)
                    if (it && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                        context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
                        PackageManager.PERMISSION_GRANTED) {
                        askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
                    }
                })
            }
        }
    }
}
