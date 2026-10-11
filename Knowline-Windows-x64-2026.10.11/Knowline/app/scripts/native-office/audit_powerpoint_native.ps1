param(
    [Parameter(Mandatory = $true)][string]$PresentationPath,
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)][string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$expectedPath = [IO.Path]::GetFullPath($PresentationPath)
$manifestFullPath = [IO.Path]::GetFullPath($ManifestPath)
$app = $null
$presentation = $null
$openedTargetByScript = $false
$fileItem = $null
$originalReadOnly = $null

function Read-Utf8Json {
    param([string]$Path)
    $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $text = [IO.File]::ReadAllText($Path, $utf8)
    if ($text.Contains([char]0xFFFD)) {
        throw "UTF-8 replacement character found in manifest: $Path"
    }
    return $text | ConvertFrom-Json
}

function Get-ActivePowerPoint {
    try { return [Runtime.InteropServices.Marshal]::GetActiveObject('PowerPoint.Application') }
    catch { return $null }
}

function Get-ExactPresentation {
    param($Application, [string]$Path)
    if ($null -eq $Application) { return $null }
    $matches = @()
    foreach ($candidate in @($Application.Presentations)) {
        try {
            $actual = [IO.Path]::GetFullPath([string]$candidate.FullName)
            if ([string]::Equals($actual, $Path, [StringComparison]::OrdinalIgnoreCase)) {
                $matches += $candidate
            }
        } catch {}
    }
    if ($matches.Count -gt 1) { throw "Multiple exact-path presentations are open: $Path" }
    if ($matches.Count -eq 1) { return $matches[0] }
    return $null
}

function Normalize-PowerPointText {
    param([string]$Text)
    if ($null -eq $Text) { return '' }
    return ([regex]::Replace($Text, "\r\n?|\n|\x0b", "`n")).TrimEnd([char]10)
}

try {
    if (!(Test-Path -LiteralPath $expectedPath)) {
        throw "Presentation does not exist: $expectedPath"
    }
    if (!(Test-Path -LiteralPath $manifestFullPath)) {
        throw "Audit manifest does not exist: $manifestFullPath"
    }

    $manifest = Read-Utf8Json -Path $manifestFullPath
    $slideIndex = if ($null -ne $manifest.slide_index) { [int]$manifest.slide_index } else { 1 }
    $renderWidth = if ($null -ne $manifest.render_width) { [int]$manifest.render_width } else { 1440 }
    $renderHeight = if ($null -ne $manifest.render_height) { [int]$manifest.render_height } else { 1080 }
    $expectedSlideCount = if ($null -ne $manifest.expected_slide_count) { [int]$manifest.expected_slide_count } else { 1 }
    $expectedShapeCount = if ($null -ne $manifest.expected_shape_count) { [int]$manifest.expected_shape_count } else { $null }
    $expectedImageCount = if ($null -ne $manifest.expected_image_count) { [int]$manifest.expected_image_count } else { $null }
    $expectedIconCount = if ($null -ne $manifest.expected_icon_count) { [int]$manifest.expected_icon_count } else { $null }
    $expectedConnectorCount = if ($null -ne $manifest.expected_connector_count) { [int]$manifest.expected_connector_count } else { $null }
    $requireFullRegistry = if ($null -ne $manifest.require_full_registry) { [bool]$manifest.require_full_registry } else { $true }
    $deliveryGate = if ($null -ne $manifest.delivery_gate) { [bool]$manifest.delivery_gate } else { $false }
    $expectedAxisConstraintCount = if ($null -ne $manifest.expected_axis_constraint_count) { [int]$manifest.expected_axis_constraint_count } else { $null }
    $expectedFormulaCount = if ($null -ne $manifest.expected_formula_count) { [int]$manifest.expected_formula_count } else { $null }
    $configurationViolations = @()
    if ($deliveryGate -and $null -eq $manifest.require_full_registry) {
        $configurationViolations += 'delivery_gate_requires_explicit_require_full_registry'
    }
    if ($deliveryGate -and -not $requireFullRegistry) {
        $configurationViolations += 'delivery_gate_requires_full_registry_true'
    }
    if ($deliveryGate -and $null -eq $expectedAxisConstraintCount) {
        $configurationViolations += 'delivery_gate_requires_expected_axis_constraint_count'
    }
    if ($deliveryGate -and $null -eq $expectedFormulaCount) {
        $configurationViolations += 'delivery_gate_requires_expected_formula_count'
    }

    $layerRank = @{
        background = 0
        path = 1
        node = 2
        complex_image = 3
        icon = 4
        text = 5
    }
    $objectLayer = @{}
    foreach ($entry in @($manifest.objects)) {
        $name = [string]$entry.name
        $layer = [string]$entry.layer
        if (!$layerRank.ContainsKey($layer)) { throw "Unknown layer '$layer' for object '$name'." }
        if ($objectLayer.ContainsKey($name)) { throw "Duplicate object in audit manifest: $name" }
        $objectLayer[$name] = $layer
    }

    $expectedText = @{}
    foreach ($entry in @($manifest.expected_text)) {
        $name = [string]$entry.name
        if ($expectedText.ContainsKey($name)) { throw "Duplicate expected_text object: $name" }
        $expectedText[$name] = Normalize-PowerPointText -Text ([string]$entry.text)
    }

    $formulaObjects = @{}
    if ($null -ne $manifest.formula_objects) {
        foreach ($entry in @($manifest.formula_objects)) {
            if ($entry -is [string]) {
                $name = [string]$entry
                $kind = 'office'
            } else {
                $name = [string]$entry.name
                $kind = if ($null -ne $entry.kind) { [string]$entry.kind } else { 'office' }
            }
            if ([string]::IsNullOrWhiteSpace($name)) { throw 'formula_objects contains an empty name.' }
            if ($formulaObjects.ContainsKey($name)) { throw "Duplicate formula object: $name" }
            if ($kind -ne 'office' -and $kind -ne 'mathtype') { throw "Unknown formula kind '$kind' for '$name'." }
            $formulaObjects[$name] = $kind
        }
    }
    $orphanTextExpectations = @(
        $expectedText.Keys |
        Where-Object { !$objectLayer.ContainsKey($_) } |
        Sort-Object
    )
    $orphanFormulaObjects = @(
        $formulaObjects.Keys |
        Where-Object { !$objectLayer.ContainsKey($_) } |
        Sort-Object
    )

    New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

    $app = Get-ActivePowerPoint
    $presentation = Get-ExactPresentation -Application $app -Path $expectedPath
    if ($null -eq $presentation) {
        $fileItem = Get-Item -LiteralPath $expectedPath -Force
        $originalReadOnly = [bool]$fileItem.IsReadOnly
        $fileItem.IsReadOnly = $true
        if ($null -eq $app) { $app = New-Object -ComObject PowerPoint.Application }
        # Open the exact owned file through COM. A corrupt package fails here
        # instead of leaving an interactive Repair dialog waiting indefinitely.
        $presentation = $app.Presentations.Open($expectedPath, -1, 0, 0)
        $openedTargetByScript = $true
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        while ($null -eq $presentation -and [DateTime]::UtcNow -lt $deadline) {
            Start-Sleep -Milliseconds 250
            $app = Get-ActivePowerPoint
            $presentation = Get-ExactPresentation -Application $app -Path $expectedPath
        }
    }
    if ($null -eq $presentation) {
        throw "PowerPoint did not expose the exact presentation within 30 seconds."
    }

    $actualPath = [IO.Path]::GetFullPath([string]$presentation.FullName)
    if (![string]::Equals($actualPath, $expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "ActivePresentation.FullName mismatch. Expected=$expectedPath Actual=$actualPath"
    }
    if (-not [bool]$presentation.ReadOnly) {
        throw "The audit presentation is not actually read-only."
    }
    if ([int]$presentation.Slides.Count -ne $expectedSlideCount) {
        throw "Slide count mismatch. Expected=$expectedSlideCount Actual=$($presentation.Slides.Count)"
    }

    $slide = $presentation.Slides.Item($slideIndex)
    $renderPath = Join-Path $OutputDirectory ("slide-{0}.png" -f $slideIndex)
    $slide.Export($renderPath, 'PNG', $renderWidth, $renderHeight)

    $shapeByName = @{}
    $nameCounts = @{}
    $connectors = @()
    $images = @()
    $icons = @()
    foreach ($shape in @($slide.Shapes)) {
        $name = [string]$shape.Name
        if (!$nameCounts.ContainsKey($name)) { $nameCounts[$name] = 0 }
        $nameCounts[$name]++
        $shapeByName[$name] = $shape
        try { if ([bool]$shape.Connector) { $connectors += $shape } } catch {}
        try { if ([int]$shape.Type -eq 11 -or [int]$shape.Type -eq 13) { $images += $shape } } catch {}
        try { if ([int]$shape.Type -eq 28) { $icons += $shape } } catch {}
    }

    $duplicates = @(
        $nameCounts.GetEnumerator() |
        Where-Object { $_.Value -ne 1 } |
        ForEach-Object { [pscustomobject]@{ name = $_.Key; count = $_.Value } }
    )
    $missingObjects = @($objectLayer.Keys | Where-Object { !$shapeByName.ContainsKey($_) } | Sort-Object)
    $unregisteredObjects = if ($requireFullRegistry) {
        @($shapeByName.Keys | Where-Object { !$objectLayer.ContainsKey($_) } | Sort-Object)
    } else {
        @()
    }

    $textBearingRegistered = @()
    foreach ($name in @($objectLayer.Keys)) {
        if (!$shapeByName.ContainsKey($name)) { continue }
        $shape = $shapeByName[$name]
        try {
            if ([int]$shape.HasTextFrame -ne 0) {
                $actualText = Normalize-PowerPointText -Text ([string]$shape.TextFrame2.TextRange.Text)
                if (-not [string]::IsNullOrWhiteSpace($actualText)) {
                    $textBearingRegistered += $name
                }
            }
        } catch {}
    }
    $missingTextExpectations = @(
        $textBearingRegistered |
        Where-Object { !$expectedText.ContainsKey($_) -and !$formulaObjects.ContainsKey($_) } |
        Sort-Object -Unique
    )

    $layerViolations = @()
    $registeredNames = @($objectLayer.Keys)
    for ($i = 0; $i -lt $registeredNames.Count; $i++) {
        for ($j = $i + 1; $j -lt $registeredNames.Count; $j++) {
            $nameA = $registeredNames[$i]
            $nameB = $registeredNames[$j]
            if (!$shapeByName.ContainsKey($nameA) -or !$shapeByName.ContainsKey($nameB)) { continue }
            $rankA = [int]$layerRank[$objectLayer[$nameA]]
            $rankB = [int]$layerRank[$objectLayer[$nameB]]
            if ($rankA -eq $rankB) { continue }
            if ($rankA -lt $rankB) {
                $lowerName = $nameA
                $upperName = $nameB
            } else {
                $lowerName = $nameB
                $upperName = $nameA
            }
            $lower = $shapeByName[$lowerName]
            $upper = $shapeByName[$upperName]
            if ([int]$lower.ZOrderPosition -ge [int]$upper.ZOrderPosition) {
                $layerViolations += [pscustomobject]@{
                    lower = $lowerName
                    lower_layer = $objectLayer[$lowerName]
                    lower_z = [int]$lower.ZOrderPosition
                    upper = $upperName
                    upper_layer = $objectLayer[$upperName]
                    upper_z = [int]$upper.ZOrderPosition
                }
            }
        }
    }

    $unconnectedEndpoints = @()
    foreach ($connector in $connectors) {
        try {
            if (-not [bool]$connector.ConnectorFormat.BeginConnected) {
                $unconnectedEndpoints += "$($connector.Name):source"
            }
            if (-not [bool]$connector.ConnectorFormat.EndConnected) {
                $unconnectedEndpoints += "$($connector.Name):target"
            }
        } catch {
            $unconnectedEndpoints += "$($connector.Name):read_error"
        }
    }

    $axisViolations = @()
    foreach ($constraint in @($manifest.axis_constraints)) {
        $sourceName = [string]$constraint.source
        $targetName = [string]$constraint.target
        $axis = [string]$constraint.axis
        if (!$shapeByName.ContainsKey($sourceName) -or !$shapeByName.ContainsKey($targetName)) {
            $axisViolations += [pscustomobject]@{
                source = $sourceName
                target = $targetName
                axis = $axis
                error = 'missing_shape'
            }
            continue
        }
        $source = $shapeByName[$sourceName]
        $target = $shapeByName[$targetName]
        if ($axis -eq 'vertical') {
            $delta = [Math]::Abs(
                ([double]$source.Left + [double]$source.Width / 2) -
                ([double]$target.Left + [double]$target.Width / 2)
            )
        } elseif ($axis -eq 'horizontal') {
            $delta = [Math]::Abs(
                ([double]$source.Top + [double]$source.Height / 2) -
                ([double]$target.Top + [double]$target.Height / 2)
            )
        } else {
            throw "Unknown axis '$axis' for $sourceName -> $targetName"
        }
        if ($delta -gt 0.1) {
            $axisViolations += [pscustomobject]@{
                source = $sourceName
                target = $targetName
                axis = $axis
                delta_pt = [Math]::Round($delta, 4)
            }
        }
    }
    if ($null -ne $expectedAxisConstraintCount -and @($manifest.axis_constraints).Count -ne $expectedAxisConstraintCount) {
        $configurationViolations += "axis_constraint_count:$(@($manifest.axis_constraints).Count)!=$expectedAxisConstraintCount"
    }

    $textOverflows = @()
    $textMismatches = @()
    foreach ($name in @($expectedText.Keys)) {
        if (!$shapeByName.ContainsKey($name)) {
            $textMismatches += [pscustomobject]@{ name = $name; error = 'missing_shape' }
            continue
        }
        $shape = $shapeByName[$name]
        try {
            $actualText = Normalize-PowerPointText -Text ([string]$shape.TextFrame2.TextRange.Text)
            if ($actualText -ne $expectedText[$name] -or $actualText.Contains([char]0xFFFD)) {
                $textMismatches += [pscustomobject]@{
                    name = $name
                    expected = $expectedText[$name]
                    actual = $actualText
                }
            }
            $availableW = [double]$shape.Width - [double]$shape.TextFrame2.MarginLeft - [double]$shape.TextFrame2.MarginRight
            $availableH = [double]$shape.Height - [double]$shape.TextFrame2.MarginTop - [double]$shape.TextFrame2.MarginBottom
            $boundW = [double]$shape.TextFrame2.TextRange.BoundWidth
            $boundH = [double]$shape.TextFrame2.TextRange.BoundHeight
            if ($boundW -gt ($availableW + 0.75) -or $boundH -gt ($availableH + 0.75)) {
                $textOverflows += [pscustomobject]@{
                    name = $name
                    bound_width = [Math]::Round($boundW, 3)
                    bound_height = [Math]::Round($boundH, 3)
                    available_width = [Math]::Round($availableW, 3)
                    available_height = [Math]::Round($availableH, 3)
                }
            }
        } catch {
            $textMismatches += [pscustomobject]@{ name = $name; error = 'text_read_error' }
        }
    }

    $formulaIssues = @()
    foreach ($name in @($formulaObjects.Keys)) {
        if (!$shapeByName.ContainsKey($name)) {
            $formulaIssues += [pscustomobject]@{ name = $name; error = 'missing_shape' }
            continue
        }
        $shape = $shapeByName[$name]
        $kind = [string]$formulaObjects[$name]
        try {
            if ($kind -eq 'office') {
                if ([int]$shape.HasTextFrame -eq 0) {
                    $formulaIssues += [pscustomobject]@{ name = $name; error = 'office_formula_has_no_text_frame' }
                    continue
                }
                $actualText = Normalize-PowerPointText -Text ([string]$shape.TextFrame2.TextRange.Text)
                if ([string]::IsNullOrWhiteSpace($actualText) -or $actualText.Contains([char]0xFFFD)) {
                    $formulaIssues += [pscustomobject]@{ name = $name; error = 'office_formula_empty_or_invalid' }
                    continue
                }
                $availableW = [double]$shape.Width - [double]$shape.TextFrame2.MarginLeft - [double]$shape.TextFrame2.MarginRight
                $availableH = [double]$shape.Height - [double]$shape.TextFrame2.MarginTop - [double]$shape.TextFrame2.MarginBottom
                $boundW = [double]$shape.TextFrame2.TextRange.BoundWidth
                $boundH = [double]$shape.TextFrame2.TextRange.BoundHeight
                if ($boundW -gt ($availableW + 0.75) -or $boundH -gt ($availableH + 0.75)) {
                    $textOverflows += [pscustomobject]@{
                        name = $name
                        bound_width = [Math]::Round($boundW, 3)
                        bound_height = [Math]::Round($boundH, 3)
                        available_width = [Math]::Round($availableW, 3)
                        available_height = [Math]::Round($availableH, 3)
                    }
                }
            } else {
                $progId = ''
                try { $progId = [string]$shape.OLEFormat.ProgID } catch {}
                if ($progId -ne 'Equation.DSMT4' -or [double]$shape.Width -le 0 -or [double]$shape.Height -le 0) {
                    $formulaIssues += [pscustomobject]@{ name = $name; error = 'invalid_mathtype_object'; prog_id = $progId }
                }
            }
        } catch {
            $formulaIssues += [pscustomobject]@{ name = $name; error = 'formula_read_error' }
        }
    }

    $countMismatches = @()
    if ($null -ne $expectedShapeCount -and [int]$slide.Shapes.Count -ne $expectedShapeCount) {
        $countMismatches += "shape_count:$($slide.Shapes.Count)!=$expectedShapeCount"
    }
    if ($null -ne $expectedImageCount -and $images.Count -ne $expectedImageCount) {
        $countMismatches += "image_count:$($images.Count)!=$expectedImageCount"
    }
    if ($null -ne $expectedIconCount -and $icons.Count -ne $expectedIconCount) {
        $countMismatches += "icon_count:$($icons.Count)!=$expectedIconCount"
    }
    if ($null -ne $expectedConnectorCount -and $connectors.Count -ne $expectedConnectorCount) {
        $countMismatches += "connector_count:$($connectors.Count)!=$expectedConnectorCount"
    }
    if ($null -ne $expectedFormulaCount -and $formulaObjects.Count -ne $expectedFormulaCount) {
        $countMismatches += "formula_count:$($formulaObjects.Count)!=$expectedFormulaCount"
    }

    $result = [ordered]@{
        ok = (
            $duplicates.Count -eq 0 -and
            $missingObjects.Count -eq 0 -and
            $unregisteredObjects.Count -eq 0 -and
            $layerViolations.Count -eq 0 -and
            $unconnectedEndpoints.Count -eq 0 -and
            $axisViolations.Count -eq 0 -and
            $textOverflows.Count -eq 0 -and
            $textMismatches.Count -eq 0 -and
            $missingTextExpectations.Count -eq 0 -and
            $orphanTextExpectations.Count -eq 0 -and
            $orphanFormulaObjects.Count -eq 0 -and
            $formulaIssues.Count -eq 0 -and
            $configurationViolations.Count -eq 0 -and
            $countMismatches.Count -eq 0
        )
        full_name = $actualPath
        read_only = [bool]$presentation.ReadOnly
        slide_count = [int]$presentation.Slides.Count
        slide_index = $slideIndex
        shape_count = [int]$slide.Shapes.Count
        image_count = $images.Count
        icon_count = $icons.Count
        connector_count = $connectors.Count
        duplicate_name_count = $duplicates.Count
        missing_object_count = $missingObjects.Count
        unregistered_object_count = $unregisteredObjects.Count
        layer_violation_count = $layerViolations.Count
        unconnected_endpoint_count = $unconnectedEndpoints.Count
        axis_violation_count = $axisViolations.Count
        text_overflow_count = $textOverflows.Count
        text_mismatch_count = $textMismatches.Count
        text_bearing_registered_count = $textBearingRegistered.Count
        expected_text_coverage_count = $expectedText.Count
        missing_text_expectation_count = $missingTextExpectations.Count
        orphan_text_expectation_count = $orphanTextExpectations.Count
        formula_object_count = $formulaObjects.Count
        orphan_formula_object_count = $orphanFormulaObjects.Count
        formula_issue_count = $formulaIssues.Count
        configuration_violation_count = $configurationViolations.Count
        count_mismatch_count = $countMismatches.Count
        render_path = $renderPath
        duplicates = $duplicates
        missing_objects = $missingObjects
        unregistered_objects = $unregisteredObjects
        layer_violations = $layerViolations
        unconnected_endpoints = $unconnectedEndpoints
        axis_violations = $axisViolations
        text_overflows = $textOverflows
        text_mismatches = $textMismatches
        missing_text_expectations = $missingTextExpectations
        orphan_text_expectations = $orphanTextExpectations
        orphan_formula_objects = $orphanFormulaObjects
        formula_issues = $formulaIssues
        configuration_violations = $configurationViolations
        count_mismatches = $countMismatches
    }
    $json = $result | ConvertTo-Json -Depth 10
    [IO.File]::WriteAllText(
        (Join-Path $OutputDirectory 'native-audit.json'),
        $json,
        (New-Object System.Text.UTF8Encoding($false))
    )
    $json
    if (-not [bool]$result.ok) {
        throw "PowerPoint native audit failed. See $(Join-Path $OutputDirectory 'native-audit.json')"
    }
} finally {
    if ($openedTargetByScript -and $null -ne $presentation) {
        try {
            $closingPath = [IO.Path]::GetFullPath([string]$presentation.FullName)
            if ([string]::Equals($closingPath, $expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
                $presentation.Close()
            }
        } catch {}
    }
    if ($null -ne $presentation) {
        try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($presentation) } catch {}
    }
    if ($null -ne $app) {
        try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($app) } catch {}
    }
    if ($null -ne $fileItem -and $null -ne $originalReadOnly) {
        try { $fileItem.IsReadOnly = [bool]$originalReadOnly } catch {}
    }
}
