param([Parameter(Mandatory=$true)][int]$ProcessId, [string]$Invoke, [switch]$OpenPanel)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$condition = New-Object System.Windows.Automation.PropertyCondition ([System.Windows.Automation.AutomationElement]::ProcessIdProperty),$ProcessId
if ($OpenPanel) {
    $windows = [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,$condition)
    foreach ($window in $windows) {
        if ($window.Current.Name -eq '任务提醒入口') {
            $buttons = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants,(New-Object System.Windows.Automation.PropertyCondition ([System.Windows.Automation.AutomationElement]::AutomationIdProperty),'launcher.open'))
            foreach ($button in $buttons) { $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke() }
        }
    }
    Start-Sleep -Milliseconds 250
}
$windows = [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,$condition)
$items = @()
foreach ($window in $windows) {
    $elements = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
    foreach ($element in $elements) {
        if ($Invoke -and $element.Current.Name -eq $Invoke) {
            $pattern = $null
            if ($element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)) { $pattern.Invoke(); $Invoke = $null }
        }
        $bounds=$element.Current.BoundingRectangle
        $rectangle=if($bounds.IsEmpty){@()}else{@($bounds.X,$bounds.Y,$bounds.Width,$bounds.Height)}
        $items += @{ name=$element.Current.Name; type=$element.Current.ControlType.ProgrammaticName; enabled=$element.Current.IsEnabled; bounds=$rectangle }
    }
}
$items | ConvertTo-Json -Compress
