from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from scipy.sparse import load_npz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from feature import (
    COLOR_TERMS,
    COMPANION_TERMS,
    DATA_DIR,
    MODEL_DIR,
    build_catalog,
    color_from_text,
    companion_from_text,
    find_kind,
    local_items,
    named_place_information,
    nearby_shopping_places,
)

try:
    from ollama import chat as ollama_chat
except ImportError:
    ollama_chat = None


OLLAMA_MODEL = 'llama3.2:3b'
FEEDBACK_FILE = DATA_DIR / 'user_feedback.csv'


class Optio:
    """Conversation and recommendation engine for a web or desktop UI."""

    def __init__(self, model_name=OLLAMA_MODEL):
        self.model_name = model_name
        try:
            self.catalog = build_catalog()
        except Exception:
            self.catalog = pd.DataFrame([{
                'item_id': 'fallback_fun',
                'kind': 'entertainment',
                'title': 'A simple fun break',
                'tags': 'relaxing fun entertainment',
                'description': 'A fallback entertainment idea while Optio reconnects to its catalog.',
                'quality': 0.5,
                'location': '',
                'source': 'Optio fallback',
                'text': 'relaxing fun entertainment',
                'audience': 'alone friends family',
            }])
        self._load_search_index()
        self._load_category_model()
        self.reset()

    def _load_search_index(self):
        vectorizer_file = MODEL_DIR / 'search_vectorizer.joblib'
        vectors_file = MODEL_DIR / 'item_vectors.npz'

        try:
            if vectorizer_file.exists() and vectors_file.exists():
                self.search_vectorizer = joblib.load(vectorizer_file)
                self.item_vectors = load_npz(vectors_file)
                if self.item_vectors.shape[0] == len(self.catalog):
                    return
        except Exception:
            pass

        self.search_vectorizer = TfidfVectorizer(
            stop_words='english', ngram_range=(1, 2), min_df=1, sublinear_tf=True
        )
        self.item_vectors = self.search_vectorizer.fit_transform(self.catalog['text'])

    def _load_category_model(self):
        model_file = MODEL_DIR / 'category_model.joblib'
        encoder_file = MODEL_DIR / 'label_encoder.joblib'
        vectorizer_file = MODEL_DIR / 'classifier_vectorizer.joblib'

        self.category_model = None
        try:
            if model_file.exists() and encoder_file.exists() and vectorizer_file.exists():
                self.category_model = joblib.load(model_file)
                self.label_encoder = joblib.load(encoder_file)
                self.classifier_vectorizer = joblib.load(vectorizer_file)
        except Exception:
            self.category_model = None

    def reset(self):
        self.language = 'en'
        self.profile = {
            'name': None,
            'taste': None,
            'companion': None,
            'country': None,
            'city': None,
            'color': None,
        }
        self.history = []
        self.last_request = ''
        self.last_titles = []
        self.last_detected_kind = None
        self.waiting_for_feedback = False
        self.waiting_to_explore = False

    def greeting(self):
        return self._reply(
            user_message='The conversation has just started.',
            goal='Greet the user as Optio, briefly say that you recommend entertainment, and ask: "What is your name?" Optio\'s own name is fixed and must never be changed.',
            fallback="Hi, I'm Optio. I can help you choose movies, songs, games, events, and fun places. What is your name?",
        )

    def _next_field(self):
        return next((key for key, value in self.profile.items() if value is None), None)

    def _next_question(self):
        if self.language == 'fr':
            questions = {
                'name': "Comment dois-je t'appeler ?",
                'taste': 'Quels films, chansons, jeux, événements ou parcs aimes-tu ?',
                'companion': 'Tu veux y aller seul, avec des amis ou avec ta famille ?',
                'country': 'Dans quel pays habites-tu ?',
                'city': 'Dans quelle ville habites-tu ?',
                'color': 'Quelle est ta couleur préférée ?',
            }
            return questions.get(self._next_field(), 'Quel type de divertissement te ferait plaisir maintenant ?')

        if self.language == 'ar':
            questions = {
                'name': 'بأي اسم تحب أن أناديك؟',
                'taste': 'ما الأفلام أو الأغاني أو الألعاب أو الفعاليات أو الحدائق التي تحبها؟',
                'companion': 'هل ستذهب وحدك أم مع الأصدقاء أم مع العائلة؟',
                'country': 'في أي دولة تعيش؟',
                'city': 'في أي مدينة تعيش؟',
                'color': 'ما لونك المفضل؟',
            }
            return questions.get(self._next_field(), 'ما نوع الترفيه الذي ترغب به الآن؟')

        if self.language == 'fa':
            questions = {
                'name': 'دوست داری با چه اسمی صدایت کنم؟',
                'taste': 'چه فیلم‌ها، آهنگ‌ها، بازی‌ها، رویدادها یا پارک‌هایی را دوست داری؟',
                'companion': 'می‌خواهی تنها، با دوستان یا با خانواده بروی؟',
                'country': 'در کدام کشور زندگی می‌کنی؟',
                'city': 'در کدام شهر زندگی می‌کنی؟',
                'color': 'رنگ مورد علاقه‌ات چیست؟',
            }
            return questions.get(self._next_field(), 'الان دوست داری چه نوع سرگرمی‌ای داشته باشی؟')

        questions = {
            'name': 'What is your name?',
            'taste': 'What movies, songs, games, events, parks, restaurants, cafes, travel places, shopping centers, or bazaars do you enjoy?',
            'companion': 'Will you go Alone, with Friends, or with Family?',
            'country': 'Which country do you live in?',
            'city': 'Which city do you live in?',
            'color': 'What is your favorite color?',
        }
        return questions.get(self._next_field(), 'What kind of entertainment are you in the mood for?')

    def _detected_language(self, message):
        text = message.lower()
        french_words = {'bonjour', 'salut', 'merci', 'suis', 'voudrais', 'français', 'francais'}
        arabic_words = {'مرحبا', 'اهلا', 'أهلا', 'شكرا', 'كيف', 'اريد', 'أريد', 'العربية', 'عربي'}
        persian_words = {'سلام', 'خوبی', 'مرسی', 'ممنون', 'فارسی', 'من', 'میخوام', 'می‌خوام', 'خداحافظ'}

        if any(word in text for word in french_words) or any(mark in text for mark in 'àâçéèêëîïôöùûüÿœ'):
            return 'fr'
        if any(word in text for word in persian_words) or any(mark in text for mark in 'پچژگکی'):
            return 'fa'
        if any(word in text for word in arabic_words) or any('\u0600' <= character <= '\u06ff' for character in text):
            return 'ar'
        return None

    def _language_request(self, message):
        text = message.lower().strip()
        supported = {
            'en': ['english', 'انگلیسی', 'انگليسي', 'الإنجليزية', 'english language'],
            'fr': ['french', 'français', 'francais', 'فرانسوی', 'الفرنسية'],
            'fa': ['farsi', 'persian', 'فارسی', 'فارسي', 'پرشین'],
            'ar': ['arabic', 'العربية', 'عربی', 'عربي'],
        }
        unsupported = [
            'spanish', 'español', 'german', 'deutsch', 'turkish', 'chinese', 'russian',
            'kurdish', 'hindi', 'urdu', 'italian', 'portuguese', 'ژاپنی', 'اسپانیایی',
            'ترکی', 'چینی', 'روسی', 'الأسبانية', 'التركية', 'الصينية', 'الروسية',
        ]
        request_words = [
            'speak', 'talk', 'language', 'reply', 'respond', 'write', 'parle', 'parlez',
            'langue', 'réponds', 'répondez', 'زبان', 'صحبت', 'حرف بزن', 'پاسخ',
            'تحدث', 'تكلم', 'لغة', 'أجب',
        ]
        is_request = any(word in text for word in request_words) or len(text.split()) <= 3
        if not is_request:
            return None

        for language, names in supported.items():
            if any(name in text for name in names):
                return language
        if any(name in text for name in unsupported):
            return 'unsupported'
        return None

    def _update_language(self, message):
        detected = self._detected_language(message)
        if detected:
            self.language = detected

    def _is_small_talk(self, message):
        text = message.lower().strip()
        foreign_casual = [
            'bonjour', 'salut', 'merci', 'comment ça va', 'comment ca va', 'qui es-tu',
            'raconte une blague', 'مرحبا', 'اهلا', 'أهلا', 'شكرا', 'كيف حالك',
            'من أنت', 'من انت', 'قل نكتة',
        ]
        if any(phrase in text for phrase in foreign_casual):
            return True

        casual = [
            'hello', 'hi', 'hey', 'how are you', 'what is up', 'thanks', 'thank you',
            'good morning', 'good evening', 'nice to meet', 'tell me a joke', 'who are you',
            'سلام', 'حالت چطوره', 'خوبی', 'مرسی', 'ممنون', 'صبح بخیر', 'شب بخیر',
            'لطیفه', 'جوک', 'تو کی هستی',
        ]
        entertainment = [
            'movie', 'film', 'game', 'music', 'song', 'event', 'concert', 'festival',
            'park', 'ride', 'watch', 'play', 'entertainment', 'فیلم', 'بازی', 'موسیقی',
            'آهنگ', 'رویداد', 'کنسرت', 'جشنواره', 'پارک', 'سرگرمی',
        ]
        return any(phrase in text for phrase in casual) or (
            text.endswith(('?', '؟')) and not any(word in text for word in entertainment)
        )

    def _is_goodbye(self, message):
        text = message.lower().strip()
        foreign_goodbyes = [
            'au revoir', 'à bientôt', 'a bientot', 'à plus', 'a plus', 'je dois y aller',
            'je vais dormir', 'bonne nuit', 'adieu', 'وداعا', 'مع السلامة',
            'يجب أن أذهب', 'يجب ان اذهب', 'سأنام', 'سانام', 'تصبح على خير',
        ]
        if any(phrase in text for phrase in foreign_goodbyes):
            return True

        goodbye_phrases = [
            'bye', 'goodbye', 'bye for now', 'see you', 'talk later',
            'i have to go', 'i need to go', 'i gotta go', 'gotta go',
            'i am going to sleep', "i'm going to sleep", 'going to sleep',
            'good night', 'time to sleep', 'i am leaving', "i'm leaving",
            'خداحافظ', 'فعلا', 'فعلاً', 'باید برم', 'باید بروم', 'می‌خوام بخوابم',
            'میخوام بخوابم', 'شب بخیر', 'بعداً می‌بینمت', 'بعدا میبینمت',
        ]
        return any(phrase in text for phrase in goodbye_phrases)

    def _is_yes(self, message):
        text = message.lower().strip()
        yes_answers = {
            'yes', 'yeah', 'yep', 'sure', 'okay', 'ok', 'of course', 'please', 'continue',
            '\u0628\u0644\u0647', '\u0622\u0631\u0647', '\u062d\u062a\u0645\u0627\u064b', '\u0646\u0639\u0645',
        }
        return text in yes_answers

    def _is_no(self, message):
        text = message.lower().strip()
        no_answers = {
            'no', 'nope', 'not now', 'nothing else', 'that is all', 'no thanks',
            '\u0646\u0647', '\u062e\u06cc\u0631', '\u0644\u0627',
        }
        return text in no_answers

    def _has_specific_request(self, message):
        text = str(message).lower()
        specific_terms = [
            'movie', 'film', 'cinema', 'game', 'gaming', 'music', 'song', 'playlist',
            'event', 'concert', 'festival', 'theme park', 'amusement park', 'ride',
            'restaurant', 'cafe', 'coffee', 'travel', 'trip', 'vacation', 'destination',
            'shopping center', 'shopping centre', 'mall', 'bazaar', 'bazar', 'market', 'souq',
            '\u0641\u06cc\u0644\u0645', '\u0628\u0627\u0632\u06cc', '\u0622\u0647\u0646\u06af', '\u0645\u0648\u0633\u06cc\u0642\u06cc',
            '\u0631\u0633\u062a\u0648\u0631\u0627\u0646', '\u06a9\u0627\u0641\u0647', '\u0633\u0641\u0631', '\u0628\u0627\u0632\u0627\u0631',
            '\u0641\u064a\u0644\u0645', '\u0644\u0639\u0628\u0629', '\u0623\u063a\u0646\u064a\u0629', '\u0645\u0648\u0633\u064a\u0642\u0649',
            '\u0645\u0637\u0639\u0645', '\u0645\u0642\u0647\u0649', '\u0633\u0641\u0631', '\u0633\u0648\u0642',
        ]
        return any(term in text for term in specific_terms)

    def _specific_place_name(self, text):
        import re

        match = re.search(r'\b(?:named|called)\s+["“]?(.+?)["”]?\s*[.!?]?$', text, re.I)
        return match.group(1).strip() if match else ''

    def _direct_answer(self, text):
        """Answer a specific request before collecting the optional preference profile."""
        requested_kind = self._detect_kind(text)
        place_name = self._specific_place_name(text)
        named_place = named_place_information(place_name, requested_kind) if place_name else pd.DataFrame()
        picks = named_place if not named_place.empty else self.recommend(text)
        self.last_detected_kind = requested_kind or self.last_detected_kind
        self.last_request = text
        self.last_titles = picks['title'].dropna().tolist()
        self.waiting_for_feedback = False
        self.waiting_to_explore = True
        kind = self.last_detected_kind or 'entertainment'

        details = []
        for _, item in picks.head(3).iterrows():
            location = f" in {item['location']}" if str(item.get('location', '')).strip() else ''
            details.append(f"{item['title']} — {item['tags']}{location}")
        summary = '; '.join(details) or 'I could not find verified catalog details for that exact place yet.'
        answer = self._reply(
            text,
            f'Answer the user\'s specific {kind} request directly using only the available candidates and their details. '
            'Do not ask profile questions. End exactly with: Is there anything else you want to explore?',
            candidates=picks,
            fallback=f'{summary}. Is there anything else you want to explore?',
        )
        return {
            'text': answer,
            'recommendations': picks[['title', 'kind', 'tags', 'location']].to_dict('records'),
            'profile_complete': False,
            'detected_kind': self.last_detected_kind,
        }

    def _name_from_text(self, message):
        import re

        match = re.search(r"(?:my name is|call me|i am|i'm)\s+([a-zA-Z-]+)", message, re.I)
        if match:
            return match.group(1).title()

        french_match = re.search(r"(?:je m'appelle|mon nom est)\s+([A-Za-zÀ-ÖØ-öø-ÿ-]+)", message, re.I)
        if french_match:
            return french_match.group(1).title()

        arabic_match = re.search(r'(?:اسمي|أنا|انا)\s+([\u0600-\u06ff]+)', message)
        if arabic_match:
            return arabic_match.group(1)

        persian_match = re.search(r'(?:اسم من|من|صدام کن)\s+([\u0600-\u06ff]+)', message)
        if persian_match:
            return persian_match.group(1)

        words = re.findall(r'[a-zA-Z-\u0600-\u06ff]+', message)
        return words[0].title() if len(words) == 1 else None

    def _companion_from_text(self, text):
        choices = {
            'seul': 'alone', 'seule': 'alone', 'amis': 'friends', 'ami': 'friends', 'famille': 'family',
            'وحدي': 'alone', 'لوحدي': 'alone', 'الأصدقاء': 'friends', 'الاصدقاء': 'friends',
            'أصدقائي': 'friends', 'اصدقائي': 'friends', 'العائلة': 'family', 'عائلتي': 'family',
            'تنها': 'alone',
            'دوستان': 'friends',
            'دوستام': 'friends',
            'خانواده': 'family',
        }
        lowered = text.lower()
        return next((value for word, value in choices.items() if word in lowered), companion_from_text(text))

    def _color_from_text(self, text):
        colors = {
            'rouge': 'red', 'orange': 'orange', 'jaune': 'yellow', 'vert': 'green', 'verte': 'green',
            'bleu': 'blue', 'bleue': 'blue', 'violet': 'purple', 'violette': 'purple', 'rose': 'pink',
            'marron': 'brown', 'noir': 'black', 'noire': 'black', 'blanc': 'white', 'blanche': 'white',
            'gris': 'gray', 'grise': 'gray', 'turquoise': 'turquoise',
            'أحمر': 'red', 'احمر': 'red', 'برتقالي': 'orange', 'أصفر': 'yellow', 'اصفر': 'yellow',
            'أخضر': 'green', 'اخضر': 'green', 'أزرق': 'blue', 'ازرق': 'blue', 'بنفسجي': 'purple',
            'وردي': 'pink', 'بني': 'brown', 'أسود': 'black', 'اسود': 'black', 'أبيض': 'white',
            'ابيض': 'white', 'رمادي': 'gray', 'فيروزي': 'turquoise',
            'قرمز': 'red', 'نارنجی': 'orange', 'زرد': 'yellow', 'سبز': 'green',
            'آبی': 'blue', 'بنفش': 'purple', 'صورتی': 'pink', 'قهوه‌ای': 'brown',
            'قهوه ای': 'brown', 'مشکی': 'black', 'سیاه': 'black', 'سفید': 'white',
            'خاکستری': 'gray', 'فیروزه‌ای': 'turquoise', 'فیروزه ای': 'turquoise',
        }
        lowered = text.lower()
        return next((value for word, value in colors.items() if word in lowered), color_from_text(text))

    def _kind_from_text(self, text):
        kinds = {
            'film': 'movie', 'film français': 'movie', 'jeu': 'game', 'musique': 'song',
            'chanson': 'song', 'concert': 'event', 'événement': 'event', 'evenement': 'event',
            'festival': 'event', 'parc': 'theme park',
            'فيلم': 'movie', 'لعبة': 'game', 'أغنية': 'song', 'اغنية': 'song', 'موسيقى': 'song',
            'حفلة': 'event', 'فعالية': 'event', 'مهرجان': 'event', 'منتزه': 'theme park', 'حديقة': 'theme park',
            'فیلم': 'movie', 'بازی': 'game', 'آهنگ': 'song', 'موسیقی': 'song',
            'کنسرت': 'event', 'رویداد': 'event', 'جشنواره': 'event', 'پارک': 'theme park',
        }
        lowered = text.lower()
        return next((value for word, value in kinds.items() if word in lowered), find_kind(text))

    def _detect_kind(self, text):
        """Use clear multilingual terms first; only trust the ML model when confident."""
        text = text.lower()
        keywords = {
            'movie': [
                'movie', 'cinema', 'watch a film', 'watch movie', 'film', 'film français',
                'فیلم', 'فيلم', 'cinéma',
            ],
            'game': [
                'video game', 'play a game', 'gaming', 'playstation', 'xbox', 'nintendo', 'steam', 'game', 'jeu',
                'بازی', 'لعبة',
            ],
            'song': [
                'playlist', 'listen to', 'listen', 'song', 'music', 'audio', 'track', 'album', 'tune',
                'rap', 'rock', 'jazz', 'chanson', 'musique',
                'آهنگ', 'موسیقی', 'اغنية', 'أغنية', 'موسيقى',
            ],
            'event': [
                'concert', 'festival', 'live show', 'event', 'spectacle', 'night out', 'show tonight',
                'things to do', 'événement', 'evenement',
                'کنسرت', 'رویداد', 'جشنواره', 'حفلة', 'فعالية', 'مهرجان',
            ],
            'theme park': [
                'theme park', 'amusement park', 'roller coaster', 'water park', 'attraction', 'fun place',
                "fun places", 'rides', "parc d'attractions",
                'پارک تفریحی', 'شهربازی', 'مدينة ملاهي', 'منتزه ترفيهي',
            ],
            'restaurant': [
                'restaurant', 'resto', 'dinner', 'lunch', 'food place', 'where to eat',
                '\u0631\u0633\u062a\u0648\u0631\u0627\u0646', '\u0645\u0637\u0639\u0645',
            ],
            'cafe': [
                'cafe', 'café', 'coffee shop', 'coffeehouse', 'coffee',
                '\u06a9\u0627\u0641\u0647', '\u0645\u0642\u0647\u0649',
            ],
            'travel place': [
                'travel', 'trip', 'vacation', 'holiday', 'destination', 'place to visit', 'tourism',
                'voyage', 'voyager', '\u0633\u0641\u0631', '\u0645\u0642\u0635\u062f', '\u0648\u062c\u0647\u0629',
            ],
            'shopping center': [
                'shopping center', 'shopping centre', 'mall', 'shopping mall', 'stores',
                '\u0645\u0631\u06a9\u0632 \u062e\u0631\u06cc\u062f', '\u0645\u062c\u062a\u0645\u0639 \u062e\u0631\u06cc\u062f',
                '\u0645\u0631\u0643\u0632 \u062a\u0633\u0648\u0642',
            ],
            'bazaar': [
                'bazaar', 'bazar', 'market', 'souq', 'souk', 'marketplace',
                '\u0628\u0627\u0632\u0627\u0631', '\u0633\u0648\u0642',
            ],
        }
        scores = {
            kind: sum(1 for word in words if word in text)
            for kind, words in keywords.items()
        }
        best_kind = max(scores, key=scores.get)
        best_score = scores[best_kind]
        tied = list(scores.values()).count(best_score) > 1

        if best_score and not tied:
            return best_kind

        if self.category_model is None:
            return None

        vector = self.classifier_vectorizer.transform([text])
        probabilities = self.category_model.predict_proba(vector)[0]
        if len(probabilities) < 2:
            return None
        top_two = np.sort(probabilities)[-2:]
        confidence = float(top_two[-1])
        margin = confidence - float(top_two[-2])

        if confidence >= 0.75 and margin >= 0.20:
            return self.label_encoder.inverse_transform([probabilities.argmax()])[0]
        return None

    def _french_fallback(self, goal, candidates):
        goal = goal.lower()
        if 'goodbye' in goal:
            return "Au revoir ! J'ai été ravi de discuter avec toi. Reviens quand tu veux pour une nouvelle idée de divertissement."
        if candidates is not None and not candidates.empty:
            return "J'ai trouvé quelques options qui correspondent à tes goûts. Dis-moi ensuite si tu les aimes ou non."
        if 'name' in goal:
            return "Ravi de faire ta connaissance. Comment dois-je t'appeler ?"
        if 'alone, friends, or family' in goal or 'alone, with friends, or with family' in goal:
            return 'Pour mieux te conseiller, tu veux y aller seul, avec des amis ou avec ta famille ?'
        if 'country' in goal:
            return 'Merci. Dans quel pays habites-tu ?'
        if 'city' in goal:
            return 'Très bien. Dans quelle ville habites-tu ?'
        if 'color' in goal:
            return 'Quelle est ta couleur préférée ?'
        if 'feedback' in goal:
            return 'Merci pour ton avis. Que voudrais-tu faire ensuite ?'
        return f'Bien sûr. {self._next_question()}'

    def _arabic_fallback(self, goal, candidates):
        goal = goal.lower()
        if 'goodbye' in goal:
            return 'مع السلامة! سعدت بالتحدث معك. عد في أي وقت عندما تريد فكرة ترفيهية جديدة.'
        if candidates is not None and not candidates.empty:
            return 'وجدت لك عدة خيارات مناسبة. أخبرني بعدها إن كنت تحبها أم لا.'
        if 'name' in goal:
            return 'سعيد بالتعرف عليك. بأي اسم تحب أن أناديك؟'
        if 'alone, friends, or family' in goal or 'alone, with friends, or with family' in goal:
            return 'لكي أقترح شيئاً مناسباً، هل ستذهب وحدك أم مع الأصدقاء أم مع العائلة؟'
        if 'country' in goal:
            return 'شكراً. في أي دولة تعيش؟'
        if 'city' in goal:
            return 'رائع. في أي مدينة تعيش؟'
        if 'color' in goal:
            return 'ما لونك المفضل؟'
        if 'feedback' in goal:
            return 'شكراً على رأيك. ماذا تريد أن تفعل بعد ذلك؟'
        return f'بالتأكيد. {self._next_question()}'

    def _localized_fallback(self, goal, candidates, fallback):
        if self.language == 'fr':
            return self._french_fallback(goal, candidates)
        if self.language == 'ar':
            return self._arabic_fallback(goal, candidates)
        if self.language != 'fa':
            return fallback

        goal = goal.lower()
        if 'goodbye' in goal:
            return 'خداحافظ! از صحبت با تو خوشحال شدم. هر وقت برای انتخاب سرگرمی کمک خواستی، من اینجا هستم.'
        if candidates is not None and not candidates.empty:
            return 'چند گزینه مناسب برایت پیدا کردم. بعد از دیدنشان به من بگو کدام را دوست داشتی یا دوست نداشتی.'
        if 'name' in goal:
            return 'خوشحالم که با تو آشنا می‌شوم. دوست داری با چه اسمی صدایت کنم؟'
        if 'alone, friends, or family' in goal or 'alone, with friends, or with family' in goal:
            return 'برای اینکه پیشنهاد بهتر باشد، می‌خواهی تنها، با دوستان یا با خانواده بروی؟'
        if 'country' in goal:
            return 'ممنون. در کدام کشور زندگی می‌کنی؟'
        if 'city' in goal:
            return 'عالیه. در کدام شهر زندگی می‌کنی؟'
        if 'color' in goal:
            return 'رنگ مورد علاقه‌ات چیست؟'
        if 'feedback' in goal:
            return 'ممنون از بازخوردت. حالا دوست داری چه کار سرگرم‌کننده‌ای انجام بدهی؟'
        return f'حتماً. {self._next_question()}'

    def _language_changed_message(self):
        messages = {
            'en': f'Of course — I will continue in English. {self._next_question()}',
            'fr': f'Bien sûr — je vais continuer en français. {self._next_question()}',
            'fa': f'حتماً — از اینجا به بعد فارسی صحبت می‌کنم. {self._next_question()}',
            'ar': f'بالتأكيد — سأتابع الحديث باللغة العربية. {self._next_question()}',
        }
        return messages[self.language]

    def _unsupported_language_message(self):
        messages = {
            'en': 'Sorry, Optio is still being improved and currently supports English, French, Farsi, and Arabic.',
            'fr': "Désolé, Optio est encore en amélioration et prend actuellement en charge l'anglais, le français, le farsi et l'arabe.",
            'fa': 'متأسفم، Optio هنوز در حال بهتر شدن است و فعلاً از انگلیسی، فرانسوی، فارسی و عربی پشتیبانی می‌کند.',
            'ar': 'عذراً، ما زال Optio قيد التطوير ويدعم حالياً الإنجليزية والفرنسية والفارسية والعربية.',
        }
        return messages[self.language]

    def _profile_summary(self):
        return ', '.join(
            f'{key}: {value or "unknown"}' for key, value in self.profile.items()
        )

    def _reply(self, user_message, goal, candidates=None, fallback=''):
        language_instruction = {
            'en': 'Reply in English.',
            'fr': 'Reply in French.',
            'fa': 'Reply in Farsi (Persian).',
            'ar': 'Reply in Arabic.',
        }[self.language]
        candidate_text = 'No recommendations yet.'
        if candidates is not None and not candidates.empty:
            candidate_text = candidates[['title', 'kind', 'tags', 'location']].to_csv(index=False)

        system = f'''You are Optio, a warm and conversational entertainment assistant.
You recommend movies, songs, games, events, theme parks, restaurants, cafes, travel places, shopping centers, and bazaars.
Your name is permanently Optio. Never ask the user to name, rename, or choose a name for you. You may only ask for the user's own name.
{language_instruction}
Be friendly, natural, and conversational, like a helpful entertainment companion. Answer the user's exact request directly. Ask one short follow-up only when it is truly needed for a better recommendation. You may answer a short harmless off-topic question or casual chat in one or two sentences, then gently return to entertainment. If reliable information is unavailable, say sorry honestly and invite the user to explore another fun activity. If the user is saying goodbye, give a warm short farewell and do not ask another question. Do not let the discussion become a general-purpose conversation.
Profile: {self._profile_summary()}.
Current requested category: {self.last_detected_kind or 'not specified'}.
When the current requested category is specified, stay strictly in that category. Do not suggest, ask about, or compare a different category unless the user explicitly changes their request.
If recommendations are provided, only mention titles from them. Never invent titles, ratings, locations, or event dates.'''
        prompt = f'User message: {user_message}\nTask: {goal}\nRecommendations:\n{candidate_text}'

        if ollama_chat is not None:
            try:
                messages = [{'role': 'system', 'content': system}] + self.history[-8:]
                messages.append({'role': 'user', 'content': prompt})
                answer = ollama_chat(model=self.model_name, messages=messages)['message']['content'].strip()
                self.history.extend([
                    {'role': 'user', 'content': user_message},
                    {'role': 'assistant', 'content': answer},
                ])
                return answer
            except Exception:
                pass

        answer = self._localized_fallback(goal, candidates, fallback) or self._next_question()
        self.history.extend([
            {'role': 'user', 'content': user_message},
            {'role': 'assistant', 'content': answer},
        ])
        return answer

    def _small_talk_reply(self, message):
        return self._reply(
            message,
            f'Reply warmly in one sentence, then naturally ask: {self._next_question()}',
            fallback=f'Nice to chat with you. {self._next_question()}',
        )

    def _save_feedback(self, feedback):
        DATA_DIR.mkdir(exist_ok=True)
        row = pd.DataFrame([{
            'name': self.profile['name'],
            'taste': self.profile['taste'],
            'companion': self.profile['companion'],
            'country': self.profile['country'],
            'city': self.profile['city'],
            'color': self.profile['color'],
            'request': self.last_request,
            'recommendations': ' | '.join(self.last_titles),
            'feedback': feedback,
            'saved_at': datetime.now().isoformat(timespec='seconds'),
        }])
        row.to_csv(FEEDBACK_FILE, mode='a', index=False, header=not FEEDBACK_FILE.exists())

    def _feedback_from_text(self, message):
        text = message.lower().strip()
        if text in {'dislike', 'disliked', 'i dislike it', 'not for me', 'bad'}:
            return 'disliked'
        if text in {'like', 'liked', 'i like it', 'love it', 'good'}:
            return 'liked'
        return None

    def _memory(self):
        if not FEEDBACK_FILE.exists() or not self.profile['name']:
            return '', set()

        history = pd.read_csv(FEEDBACK_FILE)
        history = history[
            history['name'].fillna('').str.lower().eq(self.profile['name'].lower())
        ]
        liked = history[history['feedback'].eq('liked')]
        disliked = history[history['feedback'].eq('disliked')]
        liked_text = ' '.join((liked['taste'].fillna('') + ' ' + liked['request'].fillna('')).tolist())
        rejected = set()
        for titles in disliked['recommendations'].dropna():
            rejected.update(title.strip().lower() for title in str(titles).split('|'))
        return liked_text, rejected

    def _predicted_kind(self, text):
        if self.category_model is None:
            return None

        vector = self.classifier_vectorizer.transform([text])
        probability = self.category_model.predict_proba(vector)[0]
        if probability.max() < 0.45:
            return None
        return self.label_encoder.inverse_transform([probability.argmax()])[0]

    def _recommend_core(self, request, count=5):
        kind = self._detect_kind(request)
        self.last_detected_kind = kind
        if kind in {'shopping center', 'bazaar'}:
            city = self.profile['city'] or ''
            country = self.profile['country'] or ''
            lower_request = request.lower()
            for marker in (' near ', ' in '):
                if marker in lower_request:
                    requested_place = request[lower_request.rfind(marker) + len(marker):].strip(' .!?')
                    if requested_place:
                        city, country = requested_place, ''
                    break
            live_places = nearby_shopping_places(city, country, kind, limit=count)
            if not live_places.empty:
                return live_places.head(count).reset_index(drop=True)

        companion = self.profile['companion'] or 'alone'
        color = self.profile['color'] or ''
        learned_taste, rejected = self._memory()
        query = ' '.join([
            self.profile['taste'] or '', request, COMPANION_TERMS[companion],
            COLOR_TERMS.get(color, ''), learned_taste,
        ])

        request_vector = self.search_vectorizer.transform([query])
        similarity = cosine_similarity(request_vector, self.item_vectors).ravel()
        result = self.catalog.copy().reset_index(drop=True)
        audience_bonus = result['audience'].str.contains(companion, regex=False).astype(float)
        rejected_item = result['title'].fillna('').str.lower().isin(rejected).astype(float)
        result['score'] = (
            0.78 * similarity + 0.22 * result['quality'] +
            0.08 * audience_bonus - 0.35 * rejected_item
        )

        if kind:
            matching = result[result['kind'].eq(kind)]
            if matching.empty:
                return result.iloc[0:0].copy()
            result = matching

        ranked = result.sort_values('score', ascending=False)
        if kind is None:
            # A broad request should show the user that Optio covers every entertainment type.
            first_from_each_kind = []
            for item_kind in ('movie', 'song', 'game', 'event', 'theme park', 'restaurant', 'cafe', 'travel place', 'shopping center', 'bazaar'):
                options = ranked[ranked['kind'].eq(item_kind)]
                if not options.empty:
                    first_from_each_kind.append(options.iloc[[0]])
            picks = pd.concat(first_from_each_kind, ignore_index=True) if first_from_each_kind else ranked.iloc[0:0]
            remaining = ranked[~ranked['item_id'].isin(picks['item_id'])]
            picks = pd.concat([picks, remaining], ignore_index=True).head(count).copy()
        else:
            picks = ranked.head(count).copy()

        nearby = local_items(self.catalog, self.profile['city'], self.profile['country'], limit=3)
        if kind:
            nearby = nearby[nearby['kind'].eq(kind)]
        if not nearby.empty:
            nearby['score'] = nearby['quality']
            picks = pd.concat([picks, nearby], ignore_index=True)
            picks = picks.drop_duplicates(['kind', 'title']).head(count)
        return picks.reset_index(drop=True)

    def recommend(self, request, count=5):
        """Return a stable recommendation table even if one source is unavailable."""
        try:
            return self._recommend_core(request, count=count)
        except Exception:
            return pd.DataFrame(columns=['item_id', 'kind', 'title', 'tags', 'description', 'quality', 'location', 'source'])

    def _reply_core(self, message):
        """Return a UI-friendly dictionary for every user message."""
        text = str(message).strip()
        if not text:
            return {'text': self._next_question(), 'recommendations': [], 'profile_complete': False}

        self._update_language(text)
        requested_language = self._language_request(text)
        if requested_language == 'unsupported':
            answer = self._unsupported_language_message()
            self.history.extend([
                {'role': 'user', 'content': text},
                {'role': 'assistant', 'content': answer},
            ])
            return {
                'text': answer,
                'recommendations': [],
                'profile_complete': self._next_field() is None,
            }

        if requested_language in {'en', 'fr', 'fa', 'ar'}:
            self.language = requested_language
            answer = self._language_changed_message()
            self.history.extend([
                {'role': 'user', 'content': text},
                {'role': 'assistant', 'content': answer},
            ])
            return {
                'text': answer,
                'recommendations': [],
                'profile_complete': self._next_field() is None,
            }

        if text.lower() in {'reset', 'reset profile', 'start over'}:
            self.reset()
            answer = self.greeting()
            return {'text': answer, 'recommendations': [], 'profile_complete': False}

        if self._is_goodbye(text):
            answer = self._reply(
                text,
                'Say a warm, short goodbye. Do not ask another question.',
                fallback='Goodbye! It was nice talking with you. Come back whenever you want another entertainment idea.',
            )
            return {
                'text': answer,
                'recommendations': [],
                'profile_complete': self._next_field() is None,
            }

        if self.waiting_to_explore:
            if self._is_yes(text):
                self.waiting_to_explore = False
                next_question = self._next_question()
                answer = self._reply(
                    text,
                    f'Acknowledge positively and continue learning their preferences by asking: {next_question}',
                    fallback=f"Great. Let's make the next idea personal. {next_question}",
                )
                return {'text': answer, 'recommendations': [], 'profile_complete': False}
            if self._is_no(text):
                self.waiting_to_explore = False
                answer = self._reply(
                    text,
                    'Give a warm, short farewell. Do not ask another question.',
                    fallback='No problem. Have a great day!',
                )
                return {'text': answer, 'recommendations': [], 'profile_complete': False}
            self.waiting_to_explore = False

        requested_kind = self._detect_kind(text)
        if requested_kind and self._has_specific_request(text):
            return self._direct_answer(text)

        field = self._next_field()
        if field and self._is_small_talk(text):
            answer = self._small_talk_reply(text)
            return {'text': answer, 'recommendations': [], 'profile_complete': False}

        if field == 'name':
            name = self._name_from_text(text)
            if name is None:
                answer = self._reply(
                    text,
                    "Briefly respond, then ask for the user's own name. Never ask the user to rename Optio.",
                    fallback="I'd love to get to know your taste. What is your name?",
                )
            else:
                self.profile['name'] = name
                answer = self._reply(
                    text,
                    'Welcome the user by name and ask what entertainment they enjoy.',
                    fallback=f'Nice to meet you, {name}. What movies, songs, games, events, or parks do you enjoy?',
                )
            return {'text': answer, 'recommendations': [], 'profile_complete': False}

        if field == 'taste':
            self.profile['taste'] = text
            self.last_detected_kind = self._detect_kind(text) or self.last_detected_kind
            answer = self._reply(
                text,
                'Acknowledge their taste and ask whether they are going Alone, with Friends, or with Family.',
                fallback='That sounds fun. Will you go Alone, with Friends, or with Family?',
            )
            return {'text': answer, 'recommendations': [], 'profile_complete': False}

        if field == 'companion':
            choice = self._companion_from_text(text)
            if choice is None:
                answer = self._reply(
                    text,
                    'Answer briefly, then ask the user to choose Alone, Friends, or Family.',
                    fallback='To make the recommendation fit, will you go Alone, with Friends, or with Family?',
                )
            else:
                self.profile['companion'] = choice
                answer = self._reply(
                    text,
                    'Confirm their choice and ask which country they live in.',
                    fallback=f'Got it — {choice.title()}. Which country do you live in?',
                )
            return {'text': answer, 'recommendations': [], 'profile_complete': False}

        if field == 'country':
            self.profile['country'] = text
            answer = self._reply(
                text,
                'Thank the user and ask which city they live in.',
                fallback='Thanks. Which city do you live in?',
            )
            return {'text': answer, 'recommendations': [], 'profile_complete': False}

        if field == 'city':
            self.profile['city'] = text
            answer = self._reply(
                text,
                'Confirm their city and ask their favorite color.',
                fallback="Great, I'll use that for nearby ideas too. What is your favorite color?",
            )
            return {'text': answer, 'recommendations': [], 'profile_complete': False}

        if field == 'color':
            color = self._color_from_text(text)
            if color is None:
                answer = self._reply(
                    text,
                    'Reply naturally, then ask for one favorite color such as Blue, Red, Green, Yellow, Purple, Pink, Orange, Black, White, Gray, Brown, or Turquoise.',
                    fallback='I use color only as a small preference clue. What is your favorite color?',
                )
            else:
                self.profile['color'] = color
                selected_kind = self.last_detected_kind
                next_request = (
                    f'What kind of {selected_kind} would you like right now?'
                    if selected_kind else 'What kind of entertainment are you in the mood for?'
                )
                answer = self._reply(
                    text,
                    f'Acknowledge their color and ask only about {selected_kind or "their chosen entertainment"}. Do not ask about another category.',
                    fallback=f'{color.title()} is a great choice. {next_request}',
                )
            return {'text': answer, 'recommendations': [], 'profile_complete': self._next_field() is None}

        feedback = self._feedback_from_text(text) if self.waiting_for_feedback else None
        if feedback:
            self._save_feedback(feedback)
            self.waiting_for_feedback = False
            answer = self._reply(
                text,
                'Thank the user for their feedback and ask what they would like to do next.',
                fallback="Thanks — I'll remember that. What would you like to do next?",
            )
            return {'text': answer, 'recommendations': [], 'profile_complete': True}

        if self._is_small_talk(text):
            answer = self._small_talk_reply(text)
            return {'text': answer, 'recommendations': [], 'profile_complete': True}

        if not self._has_specific_request(text):
            answer = self._reply(
                text,
                'Reply naturally and ask which specific entertainment, place, or activity the user wants to explore. Do not give recommendations yet.',
                fallback='What specific fun thing would you like to explore? You can ask for a movie, game, song, café, restaurant, event, travel place, mall, or bazaar.',
            )
            return {'text': answer, 'recommendations': [], 'profile_complete': True}

        picks = self.recommend(text)
        self.last_request = text
        self.last_titles = picks['title'].dropna().tolist()
        self.waiting_for_feedback = not picks.empty
        selected_kind = self.last_detected_kind
        category_instruction = (
            f'Keep the reply strictly focused on {selected_kind}. Do not mention or ask about other entertainment categories. '
            f'Give a warm, short {selected_kind} recommendation based only on the available candidates. Ask for Like or Dislike feedback.'
            if selected_kind else
            'Give a warm, short recommendation based on the available candidates. Ask for Like or Dislike feedback.'
        )
        answer = self._reply(
            text,
            category_instruction,
            candidates=picks,
            fallback=(
                f'I found a few {selected_kind} options that fit your taste. Tell me Like or Dislike after you look through them.'
                if selected_kind else 'I found a few options that fit your taste. Tell me Like or Dislike after you look through them.'
            ),
        )
        return {
            'text': answer,
            'recommendations': picks[['title', 'kind', 'tags', 'location']].to_dict('records'),
            'profile_complete': True,
            'detected_kind': self.last_detected_kind,
        }

    def _recovery_response(self):
        messages = {
            'en': "I'm sorry, I couldn't get a reliable answer for that right now. Tell me another fun thing you'd like to do and I'll help.",
            'fr': "Désolé, je n'ai pas pu obtenir une réponse fiable pour le moment. Dis-moi une autre activité sympa à explorer et je t'aide.",
            'fa': 'ببخشید، فعلاً نتوانستم جواب مطمئنی برای این پیدا کنم. یک سرگرمی دیگر بگو تا کمکت کنم.',
            'ar': 'عذراً، لم أتمكن من الحصول على إجابة موثوقة الآن. أخبرني عن نشاط ممتع آخر وسأساعدك.',
        }
        answer = messages.get(getattr(self, 'language', 'en'), messages['en'])
        try:
            self.history.extend([
                {'role': 'assistant', 'content': answer},
            ])
        except Exception:
            pass
        return {
            'text': answer,
            'recommendations': [],
            'profile_complete': False,
            'detected_kind': None,
        }

    def reply(self, message):
        """Always return a safe, conversational response to the UI."""
        try:
            response = self._reply_core(message)
            if isinstance(response, dict) and str(response.get('text', '')).strip():
                return response
        except Exception:
            pass
        return self._recovery_response()


if __name__ == '__main__':
    bot = Optio()
    print(f'Optio: {bot.greeting()}')
    while True:
        user_text = input('You: ').strip()
        if user_text.lower() in {'quit', 'exit'}:
            break
        response = bot.reply(user_text)
        print(f"Optio: {response['text']}")
        for item in response['recommendations']:
            print(f"  - {item['title']} ({item['kind']})")
