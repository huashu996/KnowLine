$ErrorActionPreference = 'Stop'

function Get-FormulaSkillExactVisiblePresentation {
    param(
        [Parameter(Mandatory = $true)][string]$PresentationPath,
        [switch]$LaunchIfMissing
    )
    $expected = [IO.Path]::GetFullPath($PresentationPath)
    function Find-ExactPresentation {
        try { $application = [Runtime.InteropServices.Marshal]::GetActiveObject('PowerPoint.Application') }
        catch { return $null }
        $matches = @()
        foreach ($candidate in @($application.Presentations)) {
            try {
                if ([string]::Equals([IO.Path]::GetFullPath([string]$candidate.FullName), $expected, [StringComparison]::OrdinalIgnoreCase)) {
                    $matches += $candidate
                }
            } catch {}
        }
        if ($matches.Count -gt 1) { throw "Multiple PowerPoint presentations have the same target path: $expected" }
        if ($matches.Count -eq 1) {
            return [pscustomobject]@{ Application = $application; Presentation = $matches[0] }
        }
        try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($application) } catch {}
        return $null
    }

    $binding = Find-ExactPresentation
    if ($null -ne $binding -or -not $LaunchIfMissing) { return $binding }
    try { $application = [Runtime.InteropServices.Marshal]::GetActiveObject('PowerPoint.Application') }
    catch { $application = New-Object -ComObject PowerPoint.Application }
    $owned = $application.Presentations.Open($expected, 0, 0, -1)
    if (-not [string]::Equals([IO.Path]::GetFullPath([string]$owned.FullName), $expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "PowerPoint did not open the exact owned file: $expected"
    }
    return [pscustomobject]@{ Application = $application; Presentation = $owned }
}
