# This is Sunflower Radio app.

"""Module containing radio metadata fetching related functions."""

import json
import random
import telnetlib
from datetime import datetime, time, timedelta
import glob

from backports.datetime_fromisoformat import MonkeyPatch
import requests
import mutagen

from sunflower import settings
from sunflower.utils import RedisMixin, Song

class Channel(RedisMixin):
    def __init__(self, endpoint, logger=None):
        super().__init__()
        from sunflower.stations import _stations
        self.backup_songs = []
        self.stations = _stations
        self.logger = logger # see watcher.py
        self.endpoint = endpoint
        self.redis_metadata_key = "sunflower:" + self.endpoint + ":metadata"
        self.redis_info_key = "sunflower:" + self.endpoint + ":info"

    @property
    def current_station_name(self):
        """Return string matching current time according to TIMETABLE dict in settings."""
        return self.get_station_info(datetime.now().time())[2]

    @staticmethod
    def get_station_info(time_, timetable=None):
        """Get info of station playing at given time.
        
        time_ must be datetime.time() instance.
        """
        MonkeyPatch.patch_fromisoformat()
        if timetable is None:
            assert hasattr(settings, "TIMETABLE"), "TIMETABLE not defined in settings."
            timetable = settings.TIMETABLE

        # fisrt, select weekday
        week_day = datetime.now().weekday()
        for t in timetable:
            # breakpoint()
            if week_day in t:
                key = t
                break
        else:
            raise RuntimeError("Jour de la semaine non supporté.")

        for t in timetable[key]:
            station = t[2]
            start, end = map(time.fromisoformat, t[:2])
            end = time(23, 59, 59) if end == time(0, 0, 0) else end
            if start < time_ < end:
                return start, end, station
        else:
            raise RuntimeError("Aucune station programmée à cet horaire.")

    @property
    def current_station(self):
        """Return Station object currently on air."""
        try:
            return self.stations.get(self.current_station_name)()
        except TypeError as exception:
            raise RuntimeError("Station '{}' non gérée.".format(self.current_station_name)) from exception
    
    def get_from_redis(self, key):
        """Get a key from Redis and return it as loaded json.

        If key is empty, return None.
        """
        stored_data = super().get_from_redis(key)
        if stored_data is None:
            return None
        return json.loads(stored_data.decode())
    
    def publish_to_redis(self, metadata):
        channel = self.endpoint
        return super().publish_to_redis(channel, metadata)

    @property
    def current_broadcast_metadata(self):
        """Retrieve metadata stored in Redis as a dict."""
        return self.get_from_redis(self.redis_metadata_key)

    @current_broadcast_metadata.setter
    def current_broadcast_metadata(self, metadata):
        """Store metadata in Redis."""
        self._redis.set(self.redis_metadata_key, json.dumps(metadata))

    @property
    def current_broadcast_info(self):
        """Retrieve card info stored in Redis as a dict."""
        return self.get_from_redis(self.redis_info_key)

    @current_broadcast_info.setter
    def current_broadcast_info(self, info):
        """Store card info in Redis."""
        self._redis.set(self.redis_info_key, json.dumps(info))


    def get_current_broadcast_info(self, metadata):
        """Return data for displaying broadcast info in player.
        
        This is for data display in player client. This method uses format_info()
        method of currently broadcasted station.
        """
        try:
            card_info = self.current_station.format_info(metadata)
            if not card_info["current_broadcast_end"]:
                card_info["current_broadcast_end"] = int(datetime.now().timestamp() + 5) * 1000
        except requests.exceptions.Timeout:
            card_info = {
                "current_thumbnail": self.current_station.station_thumbnail,
                "current_station": self.current_station.station_name,
                "current_broadcast_title": "Métadonnées indisponibles",
                "current_show_title": "Métadonnées indisponibles",
                "current_broadcast_summary": "Les métadonnées n'ont pas pu être récupérées : le serveur de la station demandée a mis trop de temps à répondre.",
                "current_broadcast_end": 0,
            }
        return card_info
    
    def get_current_broadcast_metadata(self):
        """Get metadata of current broadcasted programm for current station.
        
        This is for pure json data exposure. This method uses get_metadata() method
        of currently broadcasted station.
        """
        try:
            metadata = self.current_station.get_metadata()
        except requests.exceptions.Timeout:
            metadata = {"error": "Metadata can't be fetched.", "end": 0}
        metadata.update({"station": self.current_station.station_name})
        return metadata

    def _handle_advertising(self, metadata, info):
        """Play backup songs if advertising is detected on currently broadcasted station."""
        if metadata["type"] == "Publicités":
            self.logger.info("Ads detected.")
            if not self.backup_songs:
                self.logger.info("Backup songs list must be generated.")
                self.backup_songs = self._parse_songs(settings.BACKUP_SONGS_GLOB_PATTERN)
            backup_song = self.backup_songs.pop(0)
            
            # tell liquidsoap to play backup song
            session = telnetlib.Telnet("localhost", 1234)
            session.write("custom_songs.push {}\n".format(backup_song.path).encode())
            session.close()

            # and update metadata
            metadata = {
                "artist": backup_song[1],
                "title": backup_song[2],
                "end": int(datetime.now().timestamp()) + backup_song[3],
                "type": "Musique",
            }
            info = {
                "current_thumbnail": self.current_station.station_thumbnail,
                "current_station": self.current_station.station_name,
                "current_broadcast_title": backup_song[1] + " • " + backup_song[2],
                "current_show_title": "Musique",
                "current_broadcast_summary": "Publicité en cours sur RTL 2. Dans un instant, retour sur la station.",
                "current_broadcast_end": metadata["end"] * 1000,
            }
        return metadata, info
    
    @staticmethod
    def _parse_songs(glob_pattern):
        """Parse songs matching glob_pattern and return a list of Song objects.
        
        Song object is a namedtuple defined in sunflower.utils module.
        """
        songs = []
        if not glob_pattern.endswith(".ogg"):
            raise RuntimeError("Only ogg files are supported.")
        for path in glob.iglob(glob_pattern):
            file = mutagen.File(path)
            try:
                songs.append(Song(
                    path,
                    file["artist"][0],
                    file["title"][0],
                    int(file.info.length),
                ))
            except KeyError as err:
                raise KeyError("Song file {} must have an artist and a title in metadata.".format(path)) from err
        random.shuffle(songs)
        return songs

    def process_radio(self):
        """Fetch metadata, and if needed do some treatment.
        
        Treatments:
        - play backup song if advertising is detected.
        """
        metadata = self.get_current_broadcast_metadata()
        info = self.get_current_broadcast_info(metadata)
        metadata, info = self._handle_advertising(metadata, info)
        self.current_broadcast_metadata = metadata
        self.current_broadcast_info = info
        self.publish_to_redis(info)
    
    def write_liquidsoap_config(self):
        with open("test.liq", "w") as f:
            f.write("#! /usr/bin/env liquidsoap\n\n")
            f.write("# log file\n")
            f.write('set("log.file.path", "~/radio/sunflower.log")\n\n')
            f.write("# activate telnet server\n")
            f.write('set("server.telnet", true)\n\n')
            f.write("# streams\n")
            for station in self.stations.values():
                formated_name = station.station_name.lower().replace(" ", "")
                f.write('{} = mksafe(input.http("{}"))\n'.format(formated_name, station.station_url))
            f.write("\n# timetable\ntimetable = switch(track_sensitive=false, [\n")
            for days, timetable in settings.TIMETABLE.items():
                prefix = (
                    ("(" + " or ".join("{}w".format(wd) for wd in days) + ") and")
                    if len(days) > 1
                    else "{}w".format(days[0])
                )
                for start, end, station_name in timetable:
                    if start.count(":") != 1 or end.count(":") != 1:
                        raise RuntimeError("Time format must be HH:MM.")
                    formated_start = start.replace(":", "h")
                    formated_end = end.replace(":", "h")
                    formated_name = station_name.lower().replace(" ", "")
                    if len(days) > 1:
                        line = "    ({{ {} {}-{} }}, {}),\n".format(prefix, formated_start, formated_end, formated_name)
                    else:
                        line = "    ({{ {}-{} }}, {}),\n".format(prefix+formated_start, prefix+formated_end, formated_name)
                    f.write(line)
            f.write("])\n\n\n")
            f.write("""radio = fallback([timetable, default])
radio = fallback(track_sensitive=false, [request.queue(id="custom_songs"), radio])

# output
output.icecast(%vorbis(quality=0.6),
    host="localhost", port=3333, password="Arkelis77",
    mount="tournesol", radio)
""")

# if __name__ == '__main__':
#     Channel().write_liquidsoap_config()
