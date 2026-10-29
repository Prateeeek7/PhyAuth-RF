on run argv
  set inPath to POSIX file (item 1 of argv)
  set outPath to POSIX file (item 2 of argv)
  tell application "Pages"
    set d to open inPath
    delay 2
    export d to outPath as PDF
    close d saving no
  end tell
end run
