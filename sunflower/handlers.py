import telnetlib
from datetime import datetime

from sunflower import settings
from sunflower.core.types import CardMetadata, MetadataType
from sunflower.utils.functions import fetch_cover_on_deezer, parse_songs


class AdsHandler:
    def __init__(self, channel):
        self.channel = channel
        self.glob_pattern = settings.BACKUP_SONGS_GLOB_PATTERN
        self.backup_songs = self._parse_songs()

    def _fetch_cover_on_deezer(self, artist, track):
        return fetch_cover_on_deezer(artist, track, self.channel.current_station.station_thumbnail)

    def _parse_songs(self):
        return parse_songs(self.glob_pattern)

    def process(self, metadata, info, logger) -> (dict(), CardMetadata):
        """Play backup songs if advertising is detected on currently broadcasted station."""
        if metadata["type"] == MetadataType.ADS:
            self.channel.logger.info("Ads detected.")
            if not self.backup_songs:
                self.channel.logger.info("Backup songs list must be generated.")
                self.backup_songs = self._parse_songs()
            backup_song = self.backup_songs.pop(0)

            # tell liquidsoap to play backup song
            session = telnetlib.Telnet("localhost", 1234)
            session.write("{}_custom_songs.push {}\n".format(self.channel.endpoint, backup_song.path).encode())
            session.close()
            
            type_ = MetadataType.MUSIC
            station = metadata["station"]
            artist = backup_song.artist
            title = backup_song.title
            thumbnail = self._fetch_cover_on_deezer(artist, title)

            # and update metadata
            metadata = {
                "artist": artist,
                "title": title,
                "end": int(datetime.now().timestamp()) + backup_song.length,
                "type": type_,
                "station": station,
                "thumbnail_src": thumbnail,
            }
            info = CardMetadata(
                current_thumbnail=thumbnail,
                current_station=station,
                current_broadcast_title=backup_song.artist + " • " + backup_song.title,
                current_show_title=type_,
                current_broadcast_summary="Publicité en cours sur {}. Dans un instant, retour sur la station.".format(station),
            )
        return metadata, info