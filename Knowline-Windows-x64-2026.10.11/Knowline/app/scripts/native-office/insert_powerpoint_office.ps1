param(
    [Parameter(Mandatory = $true)][string]$PresentationPath,
    [Parameter(Mandatory = $true)][string]$ManifestPath
)

$ErrorActionPreference = 'Stop'
$presentationFile = [IO.Path]::GetFullPath($PresentationPath)
Set-Variable -Name AUTHORIZED_TARGET_PPTX -Value $presentationFile -Option ReadOnly -Scope Script
$manifestFile = [IO.Path]::GetFullPath($ManifestPath)
$manifest = [IO.File]::ReadAllText($manifestFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
$equations = @($manifest.equations)
$textObjects = @($manifest.text_objects)
if ([string]$manifest.mode -ne 'Office' -or ($equations.Count -eq 0 -and $textObjects.Count -eq 0)) { throw 'Office manifest contains no native preparation objects.' }

. (Join-Path $PSScriptRoot 'powerpoint_window_binding.ps1')
$binding = Get-FormulaSkillExactVisiblePresentation -PresentationPath $presentationFile -LaunchIfMissing
$powerPoint = $binding.Application
$presentation = $binding.Presentation
$results = @()
try {
    if (-not [string]::Equals([IO.Path]::GetFullPath([string]$presentation.FullName), $AUTHORIZED_TARGET_PPTX, [StringComparison]::OrdinalIgnoreCase)) { throw 'Office target path mismatch' }
    # Selection commands are necessary for equations only. Plain text layout
    # uses the exact presentation object and does not require focus.
    if ($equations.Count -gt 0) {
        $ownedWindow = $presentation.Windows.Item(1)
        $ownedWindow.WindowState = 1
        $ownedWindow.ViewType = 1
        $ownedWindow.Activate()
        if ($null -eq $powerPoint.ActivePresentation -or -not [string]::Equals([IO.Path]::GetFullPath([string]$powerPoint.ActivePresentation.FullName), $AUTHORIZED_TARGET_PPTX, [StringComparison]::OrdinalIgnoreCase)) { throw 'The exact owned presentation is not active.' }
    }
    foreach ($item in $equations) {
        $target = $item.target
        $slideIndex = [int]$target.slide_index
        if ($slideIndex -lt 1 -or $slideIndex -gt $presentation.Slides.Count) { throw "Invalid slide for $($item.id): $slideIndex" }
        $slide = $presentation.Slides.Item($slideIndex)
        $ownedWindow.WindowState = 1
        $ownedWindow.Activate()
        $ownedWindow.View.GotoSlide($slideIndex)
        if ([string]$target.type -eq 'powerpoint_shape') {
            try { $equation = $slide.Shapes.Item([string]$target.shape_name) } catch { throw "PowerPoint target not found for $($item.id)" }
        }
        elseif ([string]$target.type -eq 'powerpoint_rect' -and @($target.rect).Count -eq 4) {
            $rect = @($target.rect | ForEach-Object { [double]$_ })
            $equation = $slide.Shapes.AddTextbox(1, $rect[0], $rect[1], $rect[2], $rect[3])
        }
        else { throw "Unsupported PowerPoint target for $($item.id): $($target.type)" }

        $left = [double]$equation.Left; $top = [double]$equation.Top; $width = [double]$equation.Width; $height = [double]$equation.Height
        try { $equation.Fill.Visible = 0; $equation.Line.Visible = 0 } catch {}
        $range = $equation.TextFrame2.TextRange
        $range.Text = [string]$item.native_linear
        $range = $equation.TextFrame2.TextRange
        $range.Font.Name = 'Cambria Math'
        $range.Font.Size = [single]$(if ($item.font_size) { $item.font_size } else { 20 })
        $equation.Select()
        $range.Select()
        $existingMath = ''
        try { $existingMath = [string]$equation.TextFrame2.TextRange.MathZones(1, 1).Text } catch {}
        if ([string]::IsNullOrWhiteSpace($existingMath)) {
            if (-not $powerPoint.CommandBars.GetEnabledMso('EquationInsertNew')) { throw 'PowerPoint native equation insertion is unavailable.' }
            $powerPoint.CommandBars.ExecuteMso('EquationInsertNew')
        }
        Start-Sleep -Milliseconds 180
        $mathText = ''
        try { $mathText = [string]$equation.TextFrame2.TextRange.MathZones(1, 1).Text } catch {}
        if ([string]::IsNullOrWhiteSpace($mathText)) { throw "PowerPoint did not create an equation for $($item.id)" }
        $range = $equation.TextFrame2.TextRange
        $range.Select()
        if (-not $powerPoint.CommandBars.GetEnabledMso('EquationProfessional')) { throw 'PowerPoint professional equation conversion is unavailable.' }
        $powerPoint.CommandBars.ExecuteMso('EquationProfessional')
        Start-Sleep -Milliseconds 220
        # Conversion may reset to the Office math default size; preserve the
        # explicit physical source size after conversion and verify it later.
        $equation.TextFrame2.TextRange.Font.Size = [single]$(if ($item.font_size) { $item.font_size } else { 20 })
        $equation.Left = $left; $equation.Top = $top; $equation.Width = $width; $equation.Height = $height
        if ([int]$equation.Type -eq 17) {
            # Invisible equation text boxes must accommodate actual math glyphs.
            # Keep the source centre and font; do not stretch the rendered math.
            $neededWidth = [double]$equation.TextFrame2.TextRange.BoundWidth + [double]$equation.TextFrame2.MarginLeft + [double]$equation.TextFrame2.MarginRight + 0.3
            $neededHeight = [double]$equation.TextFrame2.TextRange.BoundHeight + [double]$equation.TextFrame2.MarginTop + [double]$equation.TextFrame2.MarginBottom + 0.3
            if ($neededWidth -gt $width) { $equation.Left = $left - ($neededWidth - $width) / 2; $equation.Width = $neededWidth }
            if ($neededHeight -gt $height) { $equation.Top = $top - ($neededHeight - $height) / 2; $equation.Height = $neededHeight }
        }
        $equation.Name = [string]$item.id
        if ([string]::IsNullOrWhiteSpace([string]$equation.TextFrame2.TextRange.MathZones(1, 1).Text)) { throw "PowerPoint equation is empty for $($item.id)" }
        $results += [pscustomobject]@{ id = [string]$item.id; object_type = 'PowerPoint.NativeEquation'; slide = $slideIndex }
        try { $powerPoint.ActiveWindow.Selection.Unselect() } catch {}
    }
    foreach ($item in $textObjects) {
        $shape = $presentation.Slides.Item(1).Shapes.Item([string]$item.name)
        if ([int]$shape.HasTextFrame -eq 0) { throw "Native text frame not found: $($item.name)" }
        $frame = $shape.TextFrame2
        $range = $frame.TextRange
        $originalText = [string]$range.Text
        $left = [double]$shape.Left; $top = [double]$shape.Top
        $width = [double]$shape.Width; $height = [double]$shape.Height
        # Source line breaks are explicit. Fixed point leading avoids Office's
        # extra default line spacing making a correctly sized caption overflow.
        $frame.WordWrap = 0
        $frame.AutoSize = 0
        $range.ParagraphFormat.LineRuleWithin = 0
        $range.ParagraphFormat.SpaceWithin = [single]$range.Font.Size
        if ([bool]$item.resize_frame) {
            # Enlarge only the invisible text frame; keep the text centre/font
            # and every visible source box/path unchanged.
            if ([int]$shape.Fill.Visible -ne 0 -or [int]$shape.Line.Visible -ne 0) { throw "Cannot fit a visible shape as a text-only frame: $($item.name)" }
            $neededWidth = [double]$range.BoundWidth + [double]$frame.MarginLeft + [double]$frame.MarginRight + 0.5
            $neededHeight = [double]$range.BoundHeight + [double]$frame.MarginTop + [double]$frame.MarginBottom + 0.5
            if ($neededWidth -gt $width) { $shape.Left = $left-($neededWidth-$width)/2; $shape.Width = $neededWidth }
            if ($neededHeight -gt $height) { $shape.Top = $top-($neededHeight-$height)/2; $shape.Height = $neededHeight }
        }
        if ([string]$frame.TextRange.Text -ne $originalText) { throw "Native text changed during layout preparation: $($item.name)" }
    }
    $presentation.Save()
}
finally {
    try {
        if ([string]::Equals([IO.Path]::GetFullPath([string]$presentation.FullName), $AUTHORIZED_TARGET_PPTX, [StringComparison]::OrdinalIgnoreCase)) { $presentation.Close() }
    } catch {}
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($presentation)
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($powerPoint)
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

[pscustomobject]@{ mode = 'Office'; target = 'PowerPoint'; output = $presentationFile; inserted_count = $results.Count; equations = $results } | ConvertTo-Json -Depth 6
