import json
import os
from datetime import date, datetime, time, timedelta

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from sunflower.mixins import RedisMixin

_stations = {}


class Station(RedisMixin):
    """Base station.

    User defined stations should inherit from this class and define following properties:
    - station_name (str)
    - station_thumbnail (str): link to station thumbnail
    """

    def __init_subclass__(cls):
        if hasattr(cls, "station_name"):
            global _stations
            _stations[cls.station_name] = cls
        return super().__init_subclass__()

    def get_from_redis(self, key):
        """Get key from redis and perform other checkings."""
        store_data = super().get_from_redis(key)
        if store_data is None:
            return None
        if key == self.REDIS_METADATA:
            if store_data["station"] != self.station_name:
                raise KeyError("Station names not matching.")
        return json.loads(store_data.decode())


    def get_metadata(self):
        """Return mapping containing metadata about current broadcast.
        
        This is data meant to be exposed as json and used by format_info() method.
        
        Required fields:
        - type: Emission|Musique|Publicités
        - metadata fields required by format_info() method (see below)
        """

    def format_info(self):
        """Format data for displaying in the card.
        
        Should return a dict containing:
        - current_thumbnail
        - current_station
        - current_broadcast_title
        - current_show_title
        - current_broadcast_summary
        - current_broadcast_end

        If empty, a given key should have "" (empty string) as value, and not None, except
        for current_broadcast_end which is False if unknown.
        """
    


class RTL2(Station):
    station_name = "RTL 2"
    station_thumbnail = "https://upload.wikimedia.org/wikipedia/fr/f/fa/RTL2_logo_2015.svg"
    _main_data_url = "https://timeline.rtl.fr/RTL2/items"
    _songs_data_url = "https://timeline.rtl.fr/RTL2/songs"

    @staticmethod
    def get_show_title(metadata):
        if time(21, 00) < datetime.now().time() < time(22, 00):
            return "RTL 2 Made in France"
        if metadata["type"] == "Musique":
            return "Musique"
        return ""

    def format_info(self):
        metadata = self.get_from_redis(self.REDIS_METADATA)
        card_info = {
            "current_thumbnail": metadata["thumbnail"],
            "current_broadcast_end": metadata["end"] * 1000, # client needs timestamp in ms
            "current_show_title": self.get_show_title(metadata),
            "current_broadcast_summary": "",
            "current_station": self.station_name,
        }
        if metadata["type"] == "Musique":
            card_info["current_broadcast_title"] = metadata["artist"] + " • " + metadata["title"]
        else: 
            card_info["current_broadcast_title"] = metadata["type"]
        return card_info

    def _fetch_metadata(self, song=False):
        """Fetch metadata from RTL 2 API.

        Proceed in two steps:
        1. First, get last item in RTL 2 timeline
        2. If it is a song, fetch from songs list (this method with song=True)
        """
        if song:
            rep = requests.get(self._songs_data_url, timeout=1)
            return json.loads(rep.content.decode())[0]
        rep = requests.get(self._main_data_url, timeout=1)
        soup = BeautifulSoup(rep.content.decode(), "html.parser")
        try:
            diffusion_type = soup.find_all("tr")[2].find_all("td")[1].text
        except IndexError:
            previous_url = "/".join(self._main_data_url.split("/")[:3]) + soup.find_all("a")[6].attrs["href"]
            rep = requests.get(previous_url, timeout=1)
            soup = BeautifulSoup(rep.content.decode(), "html.parser")
            try:
                diffusion_type = soup.find_all("tr")[2].find_all("td")[1].text
            except:
                raise RuntimeError("Le titre de la chanson ne peut pas être trouvé.")
        if diffusion_type == "Pubs":
            return {"type": "Publicités", "end": 0}
        if diffusion_type != "Musique":
            return {"type": "Intermède", "end": 0}
        else:
            return self._fetch_metadata(True)

    def get_metadata(self):
        """Return mapping containing info about current song.

        If music: {"type": "Musique", "artist": artist, "title": title}
        If ads: "type": Publicités"
        Else: "type": "Intermède"

        Moreover, returns other metadata for postprocessing.
        end datetime object

        To sum up, here are the keys of returned mapping:
        - type: str
        - end: timestamp (int) or 0 if unknown
        - artist: str (optionnal)
        - title: str (optionnal)
        """
        fetched_data = self._fetch_metadata()
        if fetched_data.get("type") in ("Publicités", "Intermède"):
            fetched_data.update({"thumbnail": self.station_thumbnail})
            return fetched_data
        metadata = {
            "artist": fetched_data["singer"],
            "title": fetched_data["title"],
            "end": int(fetched_data["end"] / 1000),
            "thumbnail": fetched_data["thumbnail"] or self.station_thumbnail,
            "type": "Musique",
        }
        return metadata


class RadioFranceStation(Station):

    @property
    def token(self):
        if os.getenv("TOKEN") is None: # in case of development server
            load_dotenv()
            if os.getenv("TOKEN") is None:
                raise RuntimeError("No token for Radio France API found.")
        return os.getenv("TOKEN")

    _grid_template = """
    {{
    grid(start: {start}, end: {end}, station: {station}) {{
        ... on DiffusionStep {{
        start
        end
        diffusion {{
            title
            standFirst
            show {{
            title
            }}
        }}
        }}
        ... on TrackStep {{
        start
        end
        track {{
            title
            albumTitle
        }}
        }}
        ... on BlankStep {{
        start
        end
        title
        }}
    }}
    }}
    """

    def format_info(self):
        metadata = self.get_from_redis(self.REDIS_METADATA)
        card_info = {
            "current_broadcast_title": metadata.get("diffusion_title", metadata["show_title"]),
            "current_thumbnail": metadata["thumbnail_src"],
            "current_broadcast_end": metadata["end"] * 1000, # client needs timestamp in ms
            "current_show_title": metadata["show_title"],
            "current_broadcast_summary": metadata["summary"],
            "current_station": self.station_name,
        }
        return card_info

    def get_metadata(self):
        fetched_data = self._fetch_metadata()
        current_show = fetched_data["data"]["grid"][0]
        next_show = fetched_data["data"]["grid"][1]
        diffusion = current_show.get("diffusion")
        metadata = {
            "type": "Emission",
            "end": int(next_show["start"]),
            "thumbnail_src": self.station_thumbnail,
        }
        if diffusion is None:
            metadata.update({
                "show_title": current_show["title"],
                "summary": "",
            })
        else:
            summary = current_show["diffusion"]["standFirst"]
            if not summary or summary == ".":
                summary = ""
            metadata.update({
                "show_title": diffusion["show"]["title"],
                "diffusion_title": diffusion["title"],
                "summary": summary,
            })
        return metadata
    

    def _fetch_metadata(self):
        start = datetime.now()
        end = datetime.now() + timedelta(minutes=120)
        query = self._grid_template.format(
            start=int(start.timestamp()),
            end=int(end.timestamp()),
            station=self._station_api_name
        )
        rep = requests.post(
            url="https://openapi.radiofrance.fr/v1/graphql?x-token={}".format(self.token),
            json={"query": query},
            timeout=4,
        )
        data = json.loads(rep.content.decode())
        return data


class FranceInter(RadioFranceStation):
    station_name = "France Inter"
    _station_api_name = "FRANCEINTER"
    station_thumbnail = "https://charte.dnm.radiofrance.fr/images/france-inter-numerique.svg"


class FranceInfo(RadioFranceStation):
    station_name = "France Info"
    _station_api_name = "FRANCEINFO"
    station_thumbnail = "https://charte.dnm.radiofrance.fr/images/franceinfo-carre.svg"


class FranceMusique(RadioFranceStation):
    station_name = "France Musique"
    _station_api_name = "FRANCEMUSIQUE"
    station_thumbnail = "https://charte.dnm.radiofrance.fr/images/france-musique-numerique.svg"


class FranceCulture(RadioFranceStation):
    station_name = "France Culture"
    _station_api_name = "FRANCECULTURE"
    station_thumbnail = "https://charte.dnm.radiofrance.fr/images/france-culture-numerique.svg"
