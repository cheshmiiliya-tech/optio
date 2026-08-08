from pathlib import Path
from urllib.request import urlretrieve
from zipfile import ZipFile

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
FMA_URL = 'https://os.unil.cloud.switch.ch/fma/fma_metadata.zip'
MUSIC_LIMIT = 30000

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
    archive = download(FMA_URL, DATA_DIR / 'fma_metadata.zip')
    tracks_file = DATA_DIR / 'fma_metadata' / 'tracks.csv'
    if not tracks_file.exists():
        with ZipFile(archive) as zipped:
            zipped.extract('fma_metadata/tracks.csv', DATA_DIR)

    tracks = pd.read_csv(tracks_file, header=[0, 1], index_col=0, low_memory=False)
    tracks = tracks.head(MUSIC_LIMIT)

    title = tracks[('track', 'title')].fillna('Unknown song').astype(str)
    artist = tracks[('artist', 'name')].fillna('').astype(str)
    genre = tracks[('track', 'genre_top')].fillna('music').astype(str)
    tags = tracks[('track', 'tags')].fillna('').astype(str)
    favorites = pd.to_numeric(tracks[('track', 'favorites')], errors='coerce').fillna(0)
    quality = (favorites / max(favorites.max(), 1)).clip(0.40, 1.0)

    return pd.DataFrame({
        'item_id': 'song_' + tracks.index.astype(str),
        'kind': 'song',
        'title': title + np.where(artist.ne(''), ' — ' + artist, ''),
        'tags': genre + ' ' + tags,
        'description': 'Song by ' + artist + '. Genre: ' + genre,
        'quality': quality,
        'location': '',
        'source': 'Free Music Archive metadata',
    })


def audience_for_row(kind, text):
    text = text.lower()
    audience = set()
    if kind in {'movie', 'theme park', 'event'} or any(word in text for word in ['family', 'kids', 'animation']):
        audience.add('family')
    if kind in {'game', 'event', 'song'} or any(word in text for word in ['party', 'comedy', 'multiplayer', 'concert']):
        audience.add('friends')
    if kind in {'movie', 'game', 'song'} or any(word in text for word in ['documentary', 'puzzle', 'drama', 'relaxing']):
        audience.add('alone')
    return ' '.join(sorted(audience or {'alone', 'friends', 'family'}))


def build_catalog(force=False):
    ensure_directories()
    if CATALOG_FILE.exists() and not force:
        return pd.read_csv(CATALOG_FILE)

    loaders = [load_movies, load_games, load_events, load_parks, load_music]
    frames = []
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
