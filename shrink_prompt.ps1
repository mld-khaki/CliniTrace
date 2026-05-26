function prompt {
    $folder = Split-Path -Leaf (Get-Location)
    "PS $folder> "
}