param(
    [switch]$NoGui
)

Set-StrictMode -Version Latest

$script:AppName = "Authon"
$script:ConfigPath = Join-Path $env:APPDATA "Authon\config.json"

function New-DefaultState {
    [ordered]@{
        target_path = ""
        profiles = @()
        active_profile = ""
        auto_switch = $false
        last_auto_runs = @{}
        last_backup = ""
    }
}

function ConvertTo-StateMap {
    param([object]$Data)

    $state = New-DefaultState
    if ($null -eq $Data) {
        return $state
    }

    foreach ($key in @("target_path", "active_profile", "last_backup")) {
        if ($Data.PSObject.Properties.Name -contains $key -and $null -ne $Data.$key) {
            $state[$key] = [string]$Data.$key
        }
    }

    if ($Data.PSObject.Properties.Name -contains "auto_switch") {
        $state["auto_switch"] = [bool]$Data.auto_switch
    }

    if ($Data.PSObject.Properties.Name -contains "profiles" -and $null -ne $Data.profiles) {
        $profiles = @()
        foreach ($profile in @($Data.profiles)) {
            $profiles += [ordered]@{
                name = [string]$profile.name
                path = [string]$profile.path
                switch_time = [string]$profile.switch_time
            }
        }
        $state["profiles"] = $profiles
    }

    if ($Data.PSObject.Properties.Name -contains "last_auto_runs" -and $null -ne $Data.last_auto_runs) {
        $runs = @{}
        foreach ($property in $Data.last_auto_runs.PSObject.Properties) {
            $runs[$property.Name] = [string]$property.Value
        }
        $state["last_auto_runs"] = $runs
    }

    return $state
}

function Load-State {
    param([string]$Path = $script:ConfigPath)

    if (-not (Test-Path -LiteralPath $Path)) {
        return New-DefaultState
    }

    try {
        $json = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        return ConvertTo-StateMap -Data ($json | ConvertFrom-Json)
    }
    catch {
        throw "Could not read Authon config: $($_.Exception.Message)"
    }
}

function Save-State {
    param(
        [hashtable]$State,
        [string]$Path = $script:ConfigPath
    )

    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory | Out-Null
    }

    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Normalize-SwitchTime {
    param([string]$Value)

    $cleaned = $Value.Trim()
    if ([string]::IsNullOrWhiteSpace($cleaned)) {
        return ""
    }

    if ($cleaned -notmatch "^(\d{1,2}):(\d{2})$") {
        throw "Switch time must be HH:MM, for example 09:30."
    }

    $hour = [int]$Matches[1]
    $minute = [int]$Matches[2]
    if ($hour -lt 0 -or $hour -gt 23 -or $minute -lt 0 -or $minute -gt 59) {
        throw "Switch time must be between 00:00 and 23:59."
    }

    return "{0:00}:{1:00}" -f $hour, $minute
}

function Test-AuthJson {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "Choose an auth.json file first."
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Auth file does not exist: $Path"
    }

    try {
        Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null
    }
    catch {
        throw "Auth file is not valid JSON: $Path ($($_.Exception.Message))"
    }
}

function Get-SafeNamePart {
    param([string]$Value)

    $cleaned = ($Value.Trim() -replace "[^A-Za-z0-9_-]+", "-").Trim("-")
    if ($cleaned.Length -gt 40) {
        return $cleaned.Substring(0, 40)
    }
    return $cleaned
}

function Backup-TargetAuth {
    param(
        [string]$TargetPath,
        [string]$ProfileName
    )

    $target = [System.IO.FileInfo]::new($TargetPath)
    $backupDir = Join-Path $target.DirectoryName "authon_backups"
    if (-not (Test-Path -LiteralPath $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir | Out-Null
    }

    $stem = [System.IO.Path]::GetFileNameWithoutExtension($target.Name)
    if ([string]::IsNullOrWhiteSpace($stem)) {
        $stem = "auth"
    }
    $suffix = $target.Extension
    if ([string]::IsNullOrWhiteSpace($suffix)) {
        $suffix = ".json"
    }

    $safeProfile = Get-SafeNamePart -Value $ProfileName
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $unique = [System.Guid]::NewGuid().ToString("N").Substring(0, 8)
    $parts = @($stem)
    if (-not [string]::IsNullOrWhiteSpace($safeProfile)) {
        $parts += $safeProfile
    }
    $parts += @($timestamp, $unique)

    $backupPath = Join-Path $backupDir ("{0}{1}" -f ($parts -join "."), $suffix)
    Copy-Item -LiteralPath $TargetPath -Destination $backupPath
    return $backupPath
}

function Activate-ProfileAuth {
    param(
        [string]$SourcePath,
        [string]$TargetPath,
        [string]$ProfileName = ""
    )

    Test-AuthJson -Path $SourcePath

    if ([string]::IsNullOrWhiteSpace($TargetPath)) {
        throw "Choose the working auth.json path."
    }

    $sourceFull = [System.IO.Path]::GetFullPath($SourcePath)
    $targetFull = [System.IO.Path]::GetFullPath($TargetPath)
    if ([string]::Equals($sourceFull, $targetFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Source auth file and working auth file are the same path."
    }

    if ((Test-Path -LiteralPath $targetFull) -and -not (Test-Path -LiteralPath $targetFull -PathType Leaf)) {
        throw "Working auth path is not a file: $targetFull"
    }

    $targetDir = Split-Path -Parent $targetFull
    if (-not (Test-Path -LiteralPath $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir | Out-Null
    }

    $backupPath = ""
    if (Test-Path -LiteralPath $targetFull -PathType Leaf) {
        $backupPath = Backup-TargetAuth -TargetPath $targetFull -ProfileName $ProfileName
    }

    $tempPath = Join-Path $targetDir (".{0}.authon-{1}.tmp" -f ([System.IO.Path]::GetFileName($targetFull)), [System.Guid]::NewGuid().ToString("N"))
    try {
        Copy-Item -LiteralPath $sourceFull -Destination $tempPath
        Move-Item -LiteralPath $tempPath -Destination $targetFull -Force
    }
    finally {
        if (Test-Path -LiteralPath $tempPath) {
            Remove-Item -LiteralPath $tempPath -Force
        }
    }

    return [ordered]@{
        source_path = $sourceFull
        target_path = $targetFull
        backup_path = $backupPath
    }
}

if ($NoGui) {
    return
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$script:State = Load-State

function Save-CurrentState {
    Save-State -State $script:State
}

function Set-Status {
    param([string]$Message)
    $script:StatusLabel.Text = $Message
}

function Get-SelectedProfileIndex {
    if ($script:ProfileList.SelectedItems.Count -eq 0) {
        return -1
    }
    return [int]$script:ProfileList.SelectedItems[0].Tag
}

function Refresh-Profiles {
    $selectedIndex = Get-SelectedProfileIndex
    $script:ProfileList.Items.Clear()
    $active = [string]$script:State["active_profile"]
    $profiles = @($script:State["profiles"])

    for ($index = 0; $index -lt $profiles.Count; $index++) {
        $profile = $profiles[$index]
        $name = [string]$profile["name"]
        $displayName = $name
        if ($name -eq $active) {
            $displayName = "* $name"
        }

        $item = [System.Windows.Forms.ListViewItem]::new($displayName)
        [void]$item.SubItems.Add([string]$profile["switch_time"])
        [void]$item.SubItems.Add([string]$profile["path"])
        $item.Tag = $index
        [void]$script:ProfileList.Items.Add($item)

        if ($index -eq $selectedIndex) {
            $item.Selected = $true
        }
    }
}

function Show-ProfileDialog {
    param([hashtable]$Profile)

    $dialog = [System.Windows.Forms.Form]::new()
    $dialog.Text = if ($Profile) { "Edit user" } else { "Add user" }
    $dialog.StartPosition = "CenterParent"
    $dialog.FormBorderStyle = "FixedDialog"
    $dialog.MaximizeBox = $false
    $dialog.MinimizeBox = $false
    $dialog.ClientSize = [System.Drawing.Size]::new(520, 178)

    $nameLabel = [System.Windows.Forms.Label]::new()
    $nameLabel.Text = "User name"
    $nameLabel.Location = [System.Drawing.Point]::new(14, 18)
    $nameLabel.AutoSize = $true
    $dialog.Controls.Add($nameLabel)

    $nameBox = [System.Windows.Forms.TextBox]::new()
    $nameBox.Location = [System.Drawing.Point]::new(110, 15)
    $nameBox.Size = [System.Drawing.Size]::new(390, 24)
    $nameBox.Text = if ($Profile) { [string]$Profile["name"] } else { "" }
    $dialog.Controls.Add($nameBox)

    $pathLabel = [System.Windows.Forms.Label]::new()
    $pathLabel.Text = "Auth file"
    $pathLabel.Location = [System.Drawing.Point]::new(14, 58)
    $pathLabel.AutoSize = $true
    $dialog.Controls.Add($pathLabel)

    $pathBox = [System.Windows.Forms.TextBox]::new()
    $pathBox.Location = [System.Drawing.Point]::new(110, 55)
    $pathBox.Size = [System.Drawing.Size]::new(305, 24)
    $pathBox.Text = if ($Profile) { [string]$Profile["path"] } else { "" }
    $dialog.Controls.Add($pathBox)

    $browseButton = [System.Windows.Forms.Button]::new()
    $browseButton.Text = "Browse"
    $browseButton.Location = [System.Drawing.Point]::new(425, 53)
    $browseButton.Size = [System.Drawing.Size]::new(75, 28)
    $browseButton.Add_Click({
        $picker = [System.Windows.Forms.OpenFileDialog]::new()
        $picker.Title = "Choose user auth.json"
        $picker.Filter = "JSON files (*.json)|*.json|All files (*.*)|*.*"
        if ($picker.ShowDialog($dialog) -eq [System.Windows.Forms.DialogResult]::OK) {
            $pathBox.Text = $picker.FileName
        }
    })
    $dialog.Controls.Add($browseButton)

    $timeLabel = [System.Windows.Forms.Label]::new()
    $timeLabel.Text = "Switch time"
    $timeLabel.Location = [System.Drawing.Point]::new(14, 98)
    $timeLabel.AutoSize = $true
    $dialog.Controls.Add($timeLabel)

    $timeBox = [System.Windows.Forms.TextBox]::new()
    $timeBox.Location = [System.Drawing.Point]::new(110, 95)
    $timeBox.Size = [System.Drawing.Size]::new(80, 24)
    $timeBox.Text = if ($Profile) { [string]$Profile["switch_time"] } else { "" }
    $dialog.Controls.Add($timeBox)

    $hintLabel = [System.Windows.Forms.Label]::new()
    $hintLabel.Text = "Optional HH:MM"
    $hintLabel.Location = [System.Drawing.Point]::new(200, 99)
    $hintLabel.AutoSize = $true
    $hintLabel.ForeColor = [System.Drawing.Color]::FromArgb(75, 85, 99)
    $dialog.Controls.Add($hintLabel)

    $saveButton = [System.Windows.Forms.Button]::new()
    $saveButton.Text = "Save"
    $saveButton.Location = [System.Drawing.Point]::new(425, 138)
    $saveButton.Size = [System.Drawing.Size]::new(75, 28)
    $dialog.AcceptButton = $saveButton
    $dialog.Controls.Add($saveButton)

    $cancelButton = [System.Windows.Forms.Button]::new()
    $cancelButton.Text = "Cancel"
    $cancelButton.Location = [System.Drawing.Point]::new(340, 138)
    $cancelButton.Size = [System.Drawing.Size]::new(75, 28)
    $cancelButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $dialog.CancelButton = $cancelButton
    $dialog.Controls.Add($cancelButton)

    $result = $null
    $saveButton.Add_Click({
        if ([string]::IsNullOrWhiteSpace($nameBox.Text)) {
            [System.Windows.Forms.MessageBox]::Show($dialog, "User name is required.", $script:AppName, "OK", "Error") | Out-Null
            return
        }
        if ([string]::IsNullOrWhiteSpace($pathBox.Text)) {
            [System.Windows.Forms.MessageBox]::Show($dialog, "Auth file is required.", $script:AppName, "OK", "Error") | Out-Null
            return
        }

        try {
            $switchTime = Normalize-SwitchTime -Value $timeBox.Text
            $script:DialogProfileResult = [ordered]@{
                name = $nameBox.Text.Trim()
                path = $pathBox.Text.Trim()
                switch_time = $switchTime
            }
            $dialog.DialogResult = [System.Windows.Forms.DialogResult]::OK
            $dialog.Close()
        }
        catch {
            [System.Windows.Forms.MessageBox]::Show($dialog, $_.Exception.Message, $script:AppName, "OK", "Error") | Out-Null
        }
    })

    $script:DialogProfileResult = $null
    if ($dialog.ShowDialog($script:Form) -eq [System.Windows.Forms.DialogResult]::OK) {
        $result = $script:DialogProfileResult
    }
    $dialog.Dispose()
    return $result
}

function Invoke-Activation {
    param(
        [hashtable]$Profile,
        [bool]$Automatic
    )

    if ($null -eq $Profile) {
        Set-Status "Select a user to activate."
        return $false
    }
    if ([string]::IsNullOrWhiteSpace($script:TargetBox.Text)) {
        Set-Status "Choose the working auth.json path first."
        return $false
    }

    try {
        $result = Activate-ProfileAuth -SourcePath ([string]$Profile["path"]) -TargetPath $script:TargetBox.Text.Trim() -ProfileName ([string]$Profile["name"])
        $script:State["target_path"] = $script:TargetBox.Text.Trim()
        $script:State["active_profile"] = [string]$Profile["name"]
        $script:State["last_backup"] = [string]$result["backup_path"]
        Save-CurrentState
        Refresh-Profiles

        $backupNote = if ([string]::IsNullOrWhiteSpace([string]$result["backup_path"])) { " No previous auth to back up." } else { " Backup: $($result["backup_path"])" }
        $prefix = if ($Automatic) { "Auto activated" } else { "Activated" }
        Set-Status "$prefix $($Profile["name"]).$backupNote"
        return $true
    }
    catch {
        Set-Status $_.Exception.Message
        if (-not $Automatic) {
            [System.Windows.Forms.MessageBox]::Show($script:Form, $_.Exception.Message, $script:AppName, "OK", "Error") | Out-Null
        }
        return $false
    }
}

$script:Form = [System.Windows.Forms.Form]::new()
$script:Form.Text = "$script:AppName - auth particle switcher"
$script:Form.StartPosition = "CenterScreen"
$script:Form.MinimumSize = [System.Drawing.Size]::new(780, 460)
$script:Form.Size = [System.Drawing.Size]::new(860, 520)
$script:Form.Font = [System.Drawing.Font]::new("Segoe UI", 9)

$titleLabel = [System.Windows.Forms.Label]::new()
$titleLabel.Text = $script:AppName
$titleLabel.Font = [System.Drawing.Font]::new("Segoe UI", 18, [System.Drawing.FontStyle]::Bold)
$titleLabel.Location = [System.Drawing.Point]::new(18, 14)
$titleLabel.AutoSize = $true
$script:Form.Controls.Add($titleLabel)

$subTitleLabel = [System.Windows.Forms.Label]::new()
$subTitleLabel.Text = "Tiny auth particle switcher"
$subTitleLabel.ForeColor = [System.Drawing.Color]::FromArgb(75, 85, 99)
$subTitleLabel.Location = [System.Drawing.Point]::new(22, 48)
$subTitleLabel.AutoSize = $true
$script:Form.Controls.Add($subTitleLabel)

$targetGroup = [System.Windows.Forms.GroupBox]::new()
$targetGroup.Text = "Working auth.json"
$targetGroup.Location = [System.Drawing.Point]::new(18, 78)
$targetGroup.Size = [System.Drawing.Size]::new(805, 68)
$targetGroup.Anchor = "Top,Left,Right"
$script:Form.Controls.Add($targetGroup)

$script:TargetBox = [System.Windows.Forms.TextBox]::new()
$script:TargetBox.Location = [System.Drawing.Point]::new(12, 27)
$script:TargetBox.Size = [System.Drawing.Size]::new(600, 24)
$script:TargetBox.Anchor = "Top,Left,Right"
$script:TargetBox.Text = [string]$script:State["target_path"]
$targetGroup.Controls.Add($script:TargetBox)

$targetBrowseButton = [System.Windows.Forms.Button]::new()
$targetBrowseButton.Text = "Browse"
$targetBrowseButton.Location = [System.Drawing.Point]::new(622, 25)
$targetBrowseButton.Size = [System.Drawing.Size]::new(78, 28)
$targetBrowseButton.Anchor = "Top,Right"
$targetGroup.Controls.Add($targetBrowseButton)

$targetSaveButton = [System.Windows.Forms.Button]::new()
$targetSaveButton.Text = "Save"
$targetSaveButton.Location = [System.Drawing.Point]::new(710, 25)
$targetSaveButton.Size = [System.Drawing.Size]::new(78, 28)
$targetSaveButton.Anchor = "Top,Right"
$targetGroup.Controls.Add($targetSaveButton)

$script:ProfileList = [System.Windows.Forms.ListView]::new()
$script:ProfileList.Location = [System.Drawing.Point]::new(18, 162)
$script:ProfileList.Size = [System.Drawing.Size]::new(682, 248)
$script:ProfileList.Anchor = "Top,Bottom,Left,Right"
$script:ProfileList.View = "Details"
$script:ProfileList.FullRowSelect = $true
$script:ProfileList.GridLines = $true
$script:ProfileList.MultiSelect = $false
[void]$script:ProfileList.Columns.Add("User", 170)
[void]$script:ProfileList.Columns.Add("Time", 80)
[void]$script:ProfileList.Columns.Add("Auth file", 410)
$script:Form.Controls.Add($script:ProfileList)

$addButton = [System.Windows.Forms.Button]::new()
$addButton.Text = "Add"
$addButton.Location = [System.Drawing.Point]::new(720, 162)
$addButton.Size = [System.Drawing.Size]::new(100, 30)
$addButton.Anchor = "Top,Right"
$script:Form.Controls.Add($addButton)

$editButton = [System.Windows.Forms.Button]::new()
$editButton.Text = "Edit"
$editButton.Location = [System.Drawing.Point]::new(720, 202)
$editButton.Size = [System.Drawing.Size]::new(100, 30)
$editButton.Anchor = "Top,Right"
$script:Form.Controls.Add($editButton)

$removeButton = [System.Windows.Forms.Button]::new()
$removeButton.Text = "Remove"
$removeButton.Location = [System.Drawing.Point]::new(720, 242)
$removeButton.Size = [System.Drawing.Size]::new(100, 30)
$removeButton.Anchor = "Top,Right"
$script:Form.Controls.Add($removeButton)

$activateButton = [System.Windows.Forms.Button]::new()
$activateButton.Text = "Activate"
$activateButton.Font = [System.Drawing.Font]::new("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
$activateButton.Location = [System.Drawing.Point]::new(720, 294)
$activateButton.Size = [System.Drawing.Size]::new(100, 34)
$activateButton.Anchor = "Top,Right"
$script:Form.Controls.Add($activateButton)

$backupButton = [System.Windows.Forms.Button]::new()
$backupButton.Text = "Backups"
$backupButton.Location = [System.Drawing.Point]::new(720, 348)
$backupButton.Size = [System.Drawing.Size]::new(100, 30)
$backupButton.Anchor = "Top,Right"
$script:Form.Controls.Add($backupButton)

$autoSwitchBox = [System.Windows.Forms.CheckBox]::new()
$autoSwitchBox.Text = "Auto switch by time"
$autoSwitchBox.Location = [System.Drawing.Point]::new(18, 424)
$autoSwitchBox.Size = [System.Drawing.Size]::new(150, 24)
$autoSwitchBox.Anchor = "Bottom,Left"
$autoSwitchBox.Checked = [bool]$script:State["auto_switch"]
$script:Form.Controls.Add($autoSwitchBox)

$script:StatusLabel = [System.Windows.Forms.Label]::new()
$script:StatusLabel.Text = "Config: $script:ConfigPath"
$script:StatusLabel.Location = [System.Drawing.Point]::new(178, 427)
$script:StatusLabel.Size = [System.Drawing.Size]::new(645, 40)
$script:StatusLabel.Anchor = "Bottom,Left,Right"
$script:StatusLabel.ForeColor = [System.Drawing.Color]::FromArgb(55, 65, 81)
$script:Form.Controls.Add($script:StatusLabel)

$targetBrowseButton.Add_Click({
    $picker = [System.Windows.Forms.OpenFileDialog]::new()
    $picker.Title = "Choose working auth.json"
    $picker.Filter = "JSON files (*.json)|*.json|All files (*.*)|*.*"
    if ($picker.ShowDialog($script:Form) -eq [System.Windows.Forms.DialogResult]::OK) {
        $script:TargetBox.Text = $picker.FileName
        $script:State["target_path"] = $picker.FileName
        Save-CurrentState
        Set-Status "Working auth path saved."
    }
})

$targetSaveButton.Add_Click({
    $script:State["target_path"] = $script:TargetBox.Text.Trim()
    Save-CurrentState
    Set-Status "Working auth path saved."
})

$addButton.Add_Click({
    $profile = Show-ProfileDialog
    if ($profile) {
        $script:State["profiles"] = @($script:State["profiles"]) + @($profile)
        Save-CurrentState
        Refresh-Profiles
        Set-Status "Added $($profile["name"])."
    }
})

$editButton.Add_Click({
    $index = Get-SelectedProfileIndex
    if ($index -lt 0) {
        Set-Status "Select a user to edit."
        return
    }
    $profiles = @($script:State["profiles"])
    $profile = Show-ProfileDialog -Profile $profiles[$index]
    if ($profile) {
        $profiles[$index] = $profile
        $script:State["profiles"] = $profiles
        Save-CurrentState
        Refresh-Profiles
        if ($index -lt $script:ProfileList.Items.Count) {
            $script:ProfileList.Items[$index].Selected = $true
        }
        Set-Status "Updated $($profile["name"])."
    }
})

$removeButton.Add_Click({
    $index = Get-SelectedProfileIndex
    if ($index -lt 0) {
        Set-Status "Select a user to remove."
        return
    }

    $profiles = @($script:State["profiles"])
    $name = [string]$profiles[$index]["name"]
    $answer = [System.Windows.Forms.MessageBox]::Show($script:Form, "Remove $name?", $script:AppName, "YesNo", "Question")
    if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) {
        return
    }

    $newProfiles = @()
    for ($i = 0; $i -lt $profiles.Count; $i++) {
        if ($i -ne $index) {
            $newProfiles += $profiles[$i]
        }
    }
    $script:State["profiles"] = $newProfiles
    if ($script:State["active_profile"] -eq $name) {
        $script:State["active_profile"] = ""
    }
    Save-CurrentState
    Refresh-Profiles
    Set-Status "Removed $name."
})

$activateButton.Add_Click({
    $index = Get-SelectedProfileIndex
    if ($index -lt 0) {
        Set-Status "Select a user to activate."
        return
    }
    $profiles = @($script:State["profiles"])
    [void](Invoke-Activation -Profile $profiles[$index] -Automatic $false)
})

$script:ProfileList.Add_DoubleClick({
    $index = Get-SelectedProfileIndex
    if ($index -ge 0) {
        $profiles = @($script:State["profiles"])
        [void](Invoke-Activation -Profile $profiles[$index] -Automatic $false)
    }
})

$backupButton.Add_Click({
    if ([string]::IsNullOrWhiteSpace($script:TargetBox.Text)) {
        Set-Status "Choose the working auth.json path first."
        return
    }
    $backupDir = Join-Path (Split-Path -Parent $script:TargetBox.Text.Trim()) "authon_backups"
    if (-not (Test-Path -LiteralPath $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir | Out-Null
    }
    Start-Process -FilePath $backupDir
})

$autoSwitchBox.Add_CheckedChanged({
    $script:State["auto_switch"] = [bool]$autoSwitchBox.Checked
    Save-CurrentState
    if ($autoSwitchBox.Checked) {
        Set-Status "Auto switch is on."
    }
    else {
        Set-Status "Auto switch is off."
    }
})

$timer = [System.Windows.Forms.Timer]::new()
$timer.Interval = 15000
$timer.Add_Tick({
    if (-not $autoSwitchBox.Checked) {
        return
    }

    $now = Get-Date
    $currentTime = $now.ToString("HH:mm")
    $today = $now.ToString("yyyy-MM-dd")
    $profiles = @($script:State["profiles"])
    $runs = $script:State["last_auto_runs"]

    foreach ($profile in $profiles) {
        $name = [string]$profile["name"]
        if ([string]$profile["switch_time"] -eq $currentTime -and (-not $runs.ContainsKey($name) -or $runs[$name] -ne $today)) {
            if (Invoke-Activation -Profile $profile -Automatic $true) {
                $runs[$name] = $today
                $script:State["last_auto_runs"] = $runs
                Save-CurrentState
            }
            break
        }
    }
})
$timer.Start()

Refresh-Profiles
[System.Windows.Forms.Application]::Run($script:Form)
