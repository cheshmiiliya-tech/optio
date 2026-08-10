from pathlib import Path
from urllib.request import urlretrieve
from zipfile import ZipFile
from functools import lru_cache

import numpy as np
import pandas as pd
import requests


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / 'data'
MODEL_DIR = ROOT / 'model'
CATALOG_FILE = DATA_DIR / 'entertainment_dataset.csv'

MOVIES_URL = 'https://files.grouplens.org/datasets/movielens/ml-latest-small.zip'
GAMES_URL = 'https://gist.githubusercontent.com/LuizKraisch/65c30cd5978a4cddb5a6f14742f6f07a/raw/games.csv'
EVENTS_URL = 'https://failteireland.azure-api.net/opendata-api/v2/events/csv'
PARKS_URL = 'https://api.themeparks.wiki/v1/destinations'
SPOTIFY_FILE = DATA_DIR / 'spotify_songs.csv'
MUSIC_LIMIT = 30000
NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
OVERPASS_URL = 'https://overpass-api.de/api/interpreter'

COLOR_TERMS = {
    'red': 'action adventure sports concert festival',
    'orange': 'comedy party games festival adventure',
    'yellow': 'comedy animation family museum outdoor',
    'green': 'park nature garden documentary relaxing',
    'blue': 'drama documentary puzzle museum relaxing',
    'purple': 'fantasy art exhibition gaming theatre',
    'pink': 'romance comedy family music',
    'brown': 'nature history board game family documentary',
    'black': 'thriller gaming art exhibition cinema',
    'white': 'documentary museum calm family',
    'gray': 'drama puzzle documentary museum',
    'turquoise': 'travel adventure water park outdoor',
}

COMPANION_TERMS = {
    'alone': 'solo relaxing story puzzle documentary',
    'friends': 'fun comedy multiplayer group party concert festival',
    'family': 'family kids animation all ages adventure theme park',
}


def ensure_directories():
    DATA_DIR.mkdir(exist_ok=True)
    MODEL_DIR.mkdir(exist_ok=True)


def text_column(frame, names, default=''):
    for name in names:
        if name in frame.columns:
            return frame[name].fillna(default).astype(str)
    return pd.Series(default, index=frame.index, dtype='object')


def number_column(frame, names, default=0.7):
    for name in names:
        if name in frame.columns:
            return pd.to_numeric(frame[name], errors='coerce').fillna(default)
    return pd.Series(default, index=frame.index, dtype='float64')


def download(url, target):
    if not target.exists():
        print(f'Downloading {target.name}...')
        urlretrieve(url, target)
    return target


def load_movies():
    archive = download(MOVIES_URL, DATA_DIR / 'ml-latest-small.zip')
    movie_folder = DATA_DIR / 'ml-latest-small'
    if not (movie_folder / 'movies.csv').exists():
        with ZipFile(archive) as zipped:
            zipped.extractall(DATA_DIR)

    movies = pd.read_csv(movie_folder / 'movies.csv')
    ratings = pd.read_csv(movie_folder / 'ratings.csv')
    mean_rating = ratings.groupby('movieId').rating.mean()

    return pd.DataFrame({
        'item_id': 'movie_' + movies['movieId'].astype(str),
        'kind': 'movie',
        'title': movies['title'].fillna('Unknown movie').astype(str),
        'tags': movies['genres'].fillna('').str.replace('|', ' ', regex=False),
        'description': movies['genres'].fillna('').str.replace('|', ' movie ', regex=False),
        'quality': (movies['movieId'].map(mean_rating).fillna(3.0) / 5).clip(0, 1),
        'location': '',
        'source': 'MovieLens Latest Small',
    })


def load_games():
    games = pd.read_csv(GAMES_URL)
    return pd.DataFrame({
        'item_id': 'game_' + games.index.astype(str),
        'kind': 'game',
        'title': text_column(games, ['Title', 'title'], 'Unknown game'),
        'tags': text_column(games, ['Genres', 'genres']).str.replace(r"[\[\]',]", ' ', regex=True),
        'description': text_column(games, ['Summary', 'summary', 'Description', 'description']),
        'quality': (number_column(games, ['Rating', 'rating'], 3.5) / 5).clip(0, 1),
        'location': '',
        'source': 'Public video-game metadata dataset',
    })


def load_events():
    events = pd.read_csv(EVENTS_URL)
    events.columns = events.columns.str.strip()
    free = text_column(events, ['Is Free To Visit']).str.lower().eq('yes')
    return pd.DataFrame({
        'item_id': 'event_' + events.index.astype(str),
        'kind': 'event',
        'title': text_column(events, ['Name', 'name'], 'Local event'),
        'tags': text_column(events, ['Event Type', 'event_type', 'Category'], 'event'),
        'description': text_column(events, ['Description', 'description']),
        'quality': np.where(free, 0.80, 0.65),
        'location': text_column(events, ['County', 'City', 'Location']),
        'source': 'Fáilte Ireland Open Data',
    })


def plain_text(value):
    if isinstance(value, dict):
        return str(next(iter(value.values()), ''))
    return str(value or '')


def load_parks():
    response = requests.get(PARKS_URL, timeout=30)
    response.raise_for_status()
    payload = response.json()
    destinations = payload.get('destinations', payload) if isinstance(payload, dict) else payload

    rows = []
    for number, destination in enumerate(destinations):
        title = plain_text(destination.get('name'))
        if title:
            rows.append({
                'item_id': f"park_{destination.get('id', number)}",
                'kind': 'theme park',
                'title': title,
                'tags': 'theme park rides attractions family adventure',
                'description': plain_text(destination.get('description')) or 'Theme park with rides and attractions.',
                'quality': 0.75,
                'location': plain_text(destination.get('location')),
                'source': 'ThemeParks.wiki API',
            })
    return pd.DataFrame(rows)


def load_music():
    """Load the included Spotify dataset locally instead of downloading FMA."""

    if not SPOTIFY_FILE.exists():
        raise FileNotFoundError(
            'spotify_songs.csv is missing from the data folder. '
            'Keep the included music dataset with this project.'
        )

    tracks = pd.read_csv(SPOTIFY_FILE).head(MUSIC_LIMIT)
    title = text_column(tracks, ['track_name'], 'Unknown song')
    artist = text_column(tracks, ['track_artist'], '')
    genre = text_column(tracks, ['playlist_genre'], 'music')
    subgenre = text_column(tracks, ['playlist_subgenre'], '')
    popularity = number_column(tracks, ['track_popularity'], 50)
    quality = (popularity / 100).clip(0.40, 1.0)
    tags = (genre + ' ' + subgenre).str.replace(r'\s+', ' ', regex=True)

    return pd.DataFrame({
        'item_id': 'song_' + tracks.index.astype(str),
        'kind': 'song',
        'title': title + np.where(artist.ne(''), ' — ' + artist, ''),
        'tags': tags,
        'description': 'Spotify playlist song by ' + artist + '. Genre: ' + genre + '.',
        'quality': quality,
        'location': '',
        'source': 'TidyTuesday Spotify playlist songs dataset',
    })


def load_dining_and_travel():
    """Small built-in catalog of real dining landmarks and travel destinations."""
    places = [
        ('restaurant', 'Noma', 'new nordic fine dining restaurant', 'Copenhagen, Denmark'),
        ('restaurant', 'Central', 'Peruvian tasting-menu restaurant', 'Lima, Peru'),
        ('restaurant', 'Osteria Francescana', 'Italian fine dining restaurant', 'Modena, Italy'),
        ('restaurant', 'Disfrutar', 'creative Mediterranean restaurant', 'Barcelona, Spain'),
        ('restaurant', 'Gaggan Anand', 'progressive Indian restaurant', 'Bangkok, Thailand'),
        ('restaurant', 'Pujol', 'Mexican restaurant and modern Mexican cuisine', 'Mexico City, Mexico'),
        ('restaurant', 'The French Laundry', 'California fine dining restaurant', 'Yountville, United States'),
        ('restaurant', 'Le Bernardin', 'seafood fine dining restaurant', 'New York, United States'),
        ('restaurant', 'Alinea', 'creative tasting-menu restaurant', 'Chicago, United States'),
        ('restaurant', 'Odette', 'French contemporary restaurant', 'Singapore'),
        ('cafe', 'Cafe Central', 'historic coffeehouse cafe and pastries', 'Vienna, Austria'),
        ('cafe', 'Cafe de Flore', 'Parisian cafe coffee and people watching', 'Paris, France'),
        ('cafe', 'Les Deux Magots', 'historic literary cafe', 'Paris, France'),
        ('cafe', 'Caffe Florian', 'historic Venetian cafe', 'Venice, Italy'),
        ('cafe', 'Cafe Tortoni', 'historic cafe and desserts', 'Buenos Aires, Argentina'),
        ('cafe', 'Cafe du Monde', 'coffee, beignets, and casual cafe', 'New Orleans, United States'),
        ('cafe', 'Cafe Majestic', 'historic art nouveau cafe', 'Porto, Portugal'),
        ('cafe', 'Antico Caffe Greco', 'historic Roman coffeehouse', 'Rome, Italy'),
        ('cafe', 'Cafe Louvre', 'historic cafe and desserts', 'Prague, Czech Republic'),
        ('cafe', 'Tomoca Coffee', 'Ethiopian coffee cafe', 'Addis Ababa, Ethiopia'),
        ('travel place', 'Kyoto', 'temples, gardens, food, and Japanese culture', 'Kyoto, Japan'),
        ('travel place', 'Santorini', 'Greek island, sea views, and villages', 'Santorini, Greece'),
        ('travel place', 'Machu Picchu', 'Incan ruins, hiking, and mountain scenery', 'Cusco, Peru'),
        ('travel place', 'Banff National Park', 'Canadian Rockies, lakes, and hiking', 'Alberta, Canada'),
        ('travel place', 'Cappadocia', 'hot-air balloons, valleys, and cave hotels', 'Nevsehir, Turkey'),
        ('travel place', 'Petra', 'archaeology, desert landscapes, and history', 'Ma\'an, Jordan'),
        ('travel place', 'Reykjavik', 'northern lights, hot springs, and Icelandic culture', 'Reykjavik, Iceland'),
        ('travel place', 'Queenstown', 'adventure sports, lakes, and mountain scenery', 'Queenstown, New Zealand'),
        ('travel place', 'Marrakech', 'markets, food, gardens, and Moroccan culture', 'Marrakech, Morocco'),
        ('travel place', 'Serengeti National Park', 'safari and wildlife travel', 'Tanzania'),
    ]
    return pd.DataFrame([
        {
            'item_id': f'place_{number}',
            'kind': kind,
            'title': title,
            'tags': tags,
            'description': f'{kind.title()} in {location}. {tags}.',
            'quality': 0.85,
            'location': location,
            'source': 'Curated global dining and travel starter catalog',
        }
        for number, (kind, title, tags, location) in enumerate(places)
    ])


def load_global_shopping():
    """Fallback catalog for shopping centres and traditional markets worldwide."""
    places = [
        ('shopping center', 'The Dubai Mall', 'shopping center fashion dining family entertainment', 'Dubai, United Arab Emirates'),
        ('shopping center', 'Mall of America', 'shopping center stores dining indoor attractions', 'Bloomington, United States'),
        ('shopping center', 'West Edmonton Mall', 'shopping center stores water park family entertainment', 'Edmonton, Canada'),
        ('shopping center', 'SM Mall of Asia', 'shopping center stores dining and waterfront attractions', 'Pasay, Philippines'),
        ('shopping center', 'Siam Paragon', 'shopping center fashion dining and entertainment', 'Bangkok, Thailand'),
        ('shopping center', 'Istanbul Cevahir', 'shopping center shops dining and entertainment', 'Istanbul, Turkey'),
        ('shopping center', 'Chadstone', 'shopping center fashion food and family activities', 'Melbourne, Australia'),
        ('shopping center', 'Westfield London', 'shopping center shops dining and entertainment', 'London, United Kingdom'),
        ('shopping center', 'Pavilion Kuala Lumpur', 'shopping center fashion food and city shopping', 'Kuala Lumpur, Malaysia'),
        ('shopping center', 'Tehran City Center', 'shopping center stores dining and entertainment', 'Tehran, Iran'),
        ('bazaar', 'Grand Bazaar', 'historic bazaar traditional shops crafts and food', 'Istanbul, Turkey'),
        ('bazaar', 'Tehran Grand Bazaar', 'historic bazaar traditional shops food and crafts', 'Tehran, Iran'),
        ('bazaar', 'Khan el-Khalili', 'historic bazaar souvenirs crafts and street food', 'Cairo, Egypt'),
        ('bazaar', 'Souq Waqif', 'traditional bazaar food crafts and local culture', 'Doha, Qatar'),
        ('bazaar', 'Chatuchak Market', 'large market fashion food art and souvenirs', 'Bangkok, Thailand'),
        ('bazaar', 'Ben Thanh Market', 'covered market food crafts and souvenirs', 'Ho Chi Minh City, Vietnam'),
        ('bazaar', 'La Boqueria', 'food market local produce and dining', 'Barcelona, Spain'),
        ('bazaar', 'Pike Place Market', 'market local food crafts and city culture', 'Seattle, United States'),
        ('bazaar', 'Jemaa el-Fnaa', 'market food crafts and cultural entertainment', 'Marrakech, Morocco'),
        ('bazaar', 'Mercado de San Miguel', 'covered food market tapas and local dining', 'Madrid, Spain'),
    ]
    return pd.DataFrame([
        {
            'item_id': f'shopping_{number}',
            'kind': kind,
            'title': title,
            'tags': tags,
            'description': f'{kind.title()} in {location}. {tags}.',
            'quality': 0.84,
            'location': location,
            'source': 'Global shopping landmark starter catalog',
        }
        for number, (kind, title, tags, location) in enumerate(places)
    ])


def _empty_places():
    return pd.DataFrame(columns=['item_id', 'kind', 'title', 'tags', 'description', 'quality', 'location', 'source'])


@lru_cache(maxsize=100)
def nearby_shopping_places(city, country, kind, limit=5):
    """Get named malls or marketplaces near the user's city from OpenStreetMap."""
    if kind not in {'shopping center', 'bazaar'} or not (city or country):
        return _empty_places()

    try:
        place_name = ', '.join(part for part in (city, country) if part)
        geocode = requests.get(
            NOMINATIM_URL,
            params={'q': place_name, 'format': 'jsonv2', 'limit': 1},
            headers={'User-Agent': 'Optio-Entertainment-Project/1.0'},
            timeout=12,
        )
        geocode.raise_for_status()
        matches = geocode.json()
        if not matches:
            return _empty_places()

        latitude = float(matches[0]['lat'])
        longitude = float(matches[0]['lon'])
        tag = '"shop"="mall"' if kind == 'shopping center' else '"amenity"="marketplace"'
        query = (
            f'[out:json][timeout:15];nwr[{tag}]'
            f'(around:18000,{latitude},{longitude});out center {int(limit)};'
        )
        response = requests.post(
            OVERPASS_URL,
            data={'data': query},
            headers={'User-Agent': 'Optio-Entertainment-Project/1.0'},
            timeout=20,
        )
        response.raise_for_status()
        elements = response.json().get('elements', [])
    except Exception:
        return _empty_places()

    rows = []
    for number, element in enumerate(elements):
        tags = element.get('tags', {})
        title = tags.get('name')
        if not title:
            continue
        rows.append({
            'item_id': f'osm_{kind.replace(" ", "_")}_{element.get("id", number)}',
            'kind': kind,
            'title': title,
            'tags': f'{kind} shopping local place',
            'description': f'Named {kind} near {place_name}, from OpenStreetMap.',
            'quality': 0.86,
            'location': place_name,
            'source': 'OpenStreetMap / Overpass',
        })
    return pd.DataFrame(rows) if rows else _empty_places()


@lru_cache(maxsize=100)
def named_place_information(place_name, kind):
    """Find available public place details for a name the user supplied."""
    if not place_name or not kind:
        return _empty_places()

    try:
        response = requests.get(
            NOMINATIM_URL,
            params={'q': place_name, 'format': 'jsonv2', 'addressdetails': 1, 'limit': 3},
            headers={'User-Agent': 'Optio-Entertainment-Project/1.0'},
            timeout=12,
        )
        response.raise_for_status()
        matches = response.json()
    except Exception:
        return _empty_places()

    rows = []
    for number, match in enumerate(matches):
        display_name = str(match.get('display_name', '')).strip()
        title = display_name.split(',')[0].strip()
        if not title:
            continue
        place_type = str(match.get('type', 'place')).replace('_', ' ')
        rows.append({
            'item_id': f'nominatim_{kind.replace(" ", "_")}_{number}',
            'kind': kind,
            'title': title,
            'tags': f'{kind} {place_type}',
            'description': f'Public place listing: {display_name}. Type: {place_type}.',
            'quality': 0.83,
            'location': display_name,
            'source': 'OpenStreetMap / Nominatim',
        })
    return pd.DataFrame(rows) if rows else _empty_places()


def audience_for_row(kind, text):
    text = text.lower()
    audience = set()
    if kind in {'movie', 'theme park', 'event', 'restaurant', 'cafe', 'travel place', 'shopping center', 'bazaar'} or any(word in text for word in ['family', 'kids', 'animation']):
        audience.add('family')
    if kind in {'game', 'event', 'song', 'restaurant', 'cafe', 'travel place', 'shopping center', 'bazaar'} or any(word in text for word in ['party', 'comedy', 'multiplayer', 'concert']):
        audience.add('friends')
    if kind in {'movie', 'game', 'song', 'cafe', 'travel place', 'shopping center', 'bazaar'} or any(word in text for word in ['documentary', 'puzzle', 'drama', 'relaxing']):
        audience.add('alone')
    return ' '.join(sorted(audience or {'alone', 'friends', 'family'}))


def build_catalog(force=False):
    ensure_directories()
    cached_catalog = None
    if CATALOG_FILE.exists() and not force:
        cached_catalog = pd.read_csv(CATALOG_FILE)
        required_kinds = {'movie', 'game', 'song', 'event', 'theme park', 'restaurant', 'cafe', 'travel place', 'shopping center', 'bazaar'}
        if required_kinds.issubset(set(cached_catalog.get('kind', pd.Series(dtype='object')).astype(str))):
            return cached_catalog
        print('Existing catalog is missing dining, travel, or shopping places, so Optio is rebuilding it.')

    loaders = [load_movies, load_games, load_events, load_parks, load_music, load_dining_and_travel, load_global_shopping]
    # Keep previously downloaded items if a remote source is temporarily unavailable.
    frames = [cached_catalog] if cached_catalog is not None else []
    for loader in loaders:
        try:
            frame = loader()
            if not frame.empty:
                frames.append(frame)
                print(f'{loader.__name__}: {len(frame):,} items')
        except Exception as error:
            print(f'{loader.__name__} skipped: {error}')

    if not frames:
        raise RuntimeError('No datasets could be loaded. Check the internet connection and run again.')

    catalog = pd.concat(frames, ignore_index=True)
    catalog = catalog.dropna(subset=['title']).drop_duplicates(['kind', 'title']).reset_index(drop=True)
    catalog['text'] = (
        catalog['title'].fillna('') + ' ' +
        catalog['tags'].fillna('') + ' ' +
        catalog['description'].fillna('')
    ).str.replace(r'\s+', ' ', regex=True).str.lower()
    catalog['audience'] = [
        audience_for_row(kind, text) for kind, text in zip(catalog['kind'], catalog['text'])
    ]
    catalog.to_csv(CATALOG_FILE, index=False)
    return catalog


def find_kind(text):
    text = text.lower()
    groups = {
        'movie': ['movie', 'film', 'cinema'],
        'game': ['game', 'steam', 'xbox', 'playstation', 'nintendo'],
        'song': ['song', 'music', 'playlist', 'listen'],
        'theme park': ['theme park', 'park', 'ride', 'roller coaster'],
        'event': ['event', 'concert', 'festival', 'show'],
        'restaurant': ['restaurant', 'resto', 'dinner', 'lunch', 'food'],
        'cafe': ['cafe', 'coffee', 'coffee shop'],
        'travel place': ['travel', 'trip', 'vacation', 'holiday', 'destination', 'visit'],
        'shopping center': ['mall', 'shopping center', 'shopping centre', 'shopping', 'stores'],
        'bazaar': ['bazaar', 'bazar', 'market', 'souq', 'souk'],
    }
    return next((kind for kind, words in groups.items() if any(word in text for word in words)), None)


def color_from_text(text):
    text = text.lower()
    return next((color for color in COLOR_TERMS if color in text), None)


def companion_from_text(text):
    text = text.lower()
    return next((choice for choice in COMPANION_TERMS if choice in text), None)


def local_items(catalog, city, country, limit=5):
    if not city and not country:
        return catalog.iloc[0:0]

    location = catalog['location'].fillna('').str.lower()
    mask = pd.Series(False, index=catalog.index)
    for place in [city, country]:
        if place:
            mask |= location.str.contains(str(place).lower(), regex=False)
    return catalog[mask].sort_values('quality', ascending=False).head(limit).copy()
