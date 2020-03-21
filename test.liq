#! /usr/bin/env liquidsoap

# log file
set("log.file", false)

# activate telnet server
set("server.telnet", true)

# default source
default = single("~/radio/franceinfo-long.ogg")

# streams
franceculture = mksafe(input.http("http://icecast.radiofrance.fr/franceculture-midfi.mp3"))
franceinfo = mksafe(input.http("http://icecast.radiofrance.fr/franceinfo-midfi.mp3"))
rtl2 = mksafe(input.http("http://streaming.radio.rtl2.fr/rtl2-1-44-128"))
francemusique = mksafe(input.http("http://icecast.radiofrance.fr/francemusique-midfi.mp3"))
franceinter = mksafe(input.http("http://icecast.radiofrance.fr/franceinter-midfi.mp3"))

# timetable
timetable = switch(track_sensitive=false, [
    ({ (1w or 2w or 3w or 4w or 5w) and 00h00-06h00 }, rtl2),
    ({ (1w or 2w or 3w or 4w or 5w) and 06h00-07h00 }, franceinfo),
    ({ (1w or 2w or 3w or 4w or 5w) and 07h00-09h00 }, franceinter),
    ({ (1w or 2w or 3w or 4w or 5w) and 09h00-12h30 }, rtl2),
    ({ (1w or 2w or 3w or 4w or 5w) and 12h30-14h30 }, franceinter),
    ({ (1w or 2w or 3w or 4w or 5w) and 14h30-18h00 }, rtl2),
    ({ (1w or 2w or 3w or 4w or 5w) and 18h00-20h00 }, franceinter),
    ({ (1w or 2w or 3w or 4w or 5w) and 20h00-21h00 }, franceinfo),
    ({ (1w or 2w or 3w or 4w or 5w) and 21h00-00h00 }, rtl2),
    ({ 6w and 00h00-06h00 }, rtl2),
    ({ 6w and 06h00-07h00 }, franceinfo),
    ({ 6w and 07h00-09h00 }, franceinter),
    ({ 6w and 09h00-13h00 }, rtl2),
    ({ 6w and 13h00-14h00 }, franceinter),
    ({ 6w and 14h00-16h00 }, rtl2),
    ({ 6w and 16h00-17h00 }, franceculture),
    ({ 6w and 17h00-20h00 }, rtl2),
    ({ 6w and 20h00-21h00 }, franceinfo),
    ({ 6w and 21h00-00h00 }, rtl2),
    ({ 7w and 00h00-06h00 }, rtl2),
    ({ 7w and 06h00-07h00 }, franceinfo),
    ({ 7w and 07h00-09h00 }, franceinter),
    ({ 7w and 09h00-13h00 }, rtl2),
    ({ 7w and 13h00-14h00 }, franceinter),
    ({ 7w and 14h00-16h00 }, rtl2),
    ({ 7w and 16h00-18h00 }, francemusique),
    ({ 7w and 18h00-19h00 }, rtl2),
    ({ 7w and 19h00-20h00 }, franceinter),
    ({ 7w and 20h00-21h00 }, franceinfo),
    ({ 7w and 21h00-00h00 }, rtl2),
])

radio = fallback([timetable, default])
radio = fallback(track_sensitive=false, [request.queue(id="custom_songs"), radio])

# output
output.icecast(%vorbis(quality=0.6),
    host="localhost", port=3333, password="Arkelis77",
    mount="tournesol", radio)
