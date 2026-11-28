"""Perception: текст → узлы, утверждения, маркеры (ADR-002).

Гибридный разбор:

- UDPipe даёт синтаксис (кто субъект, кто объект, где предлог);
- pymorphy2 даёт леммы и часть речи;
- правила ниже переводят структуру в 4 базовых типа связей ADR-001.

Правила привязаны к структуре и категориям, а не к списку слов.
Если синтаксическая модель недоступна, включается эвристический fallback.
"""

from __future__ import annotations

import re
from pathlib import Path

from griga.config import Config, load_config
from griga.graph.node import NodeType
from griga.graph.relations import RelationType
from griga.perception.models import (
    USER_LEMMA,
    USER_NAME_LABEL,
    Markers,
    Mention,
    ParseResult,
    Polarity,
    SpeechAct,
    Statement,
)
from griga.perception.morphology import Morphology, normalize_word
from griga.perception.syntax import DependencyParser, SyntaxToken, SyntaxTree


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# --- закрытые лексиконы маркеров (не растут как правила графа) ---------

_GREETINGS: tuple[str, ...] = (
    "доброе утро",
    "добрый день",
    "добрый вечер",
    "доброй ночи",
    "здравствуйте",
    "приветствую",
    "здравствуй",
    "привет",
    "здорово",
    "салют",
    "хай",
)
_GREETING_LEMMAS = frozenset(
    {
        "привет",
        "приветствие",
        "здравствуй",
        "здравствуйте",
        "здорово",
        "салют",
        "хай",
    }
)

_QUESTION_WORDS = frozenset(
    {
        "кто",
        "что",
        "где",
        "когда",
        "почему",
        "зачем",
        "как",
        "какой",
        "какая",
        "какие",
        "каков",
        "чей",
        "сколько",
        "куда",
        "откуда",
        "разве",
        "неужели",
    }
)

# слово → метка эмоции
_EMOTION_LEXICON: dict[str, str] = {
    "радость": "радость",
    "радостно": "радость",
    "рад": "радость",
    "рада": "радость",
    "счастлив": "радость",
    "счастлива": "радость",
    "весело": "радость",
    "отлично": "радость",
    "супер": "радость",
    "класс": "радость",
    "ура": "радость",
    "грусть": "грусть",
    "грустно": "грусть",
    "печаль": "грусть",
    "печально": "грусть",
    "тоска": "грусть",
    "плохо": "грусть",
    "устал": "усталость",
    "устала": "усталость",
    "усталость": "усталость",
    "злость": "агрессия",
    "злюсь": "агрессия",
    "злой": "агрессия",
    "злая": "агрессия",
    "бесит": "агрессия",
    "ненавижу": "агрессия",
    "страх": "тревога",
    "страшно": "тревога",
    "тревога": "тревога",
    "тревожно": "тревога",
    "боюсь": "тревога",
    "обида": "обида",
    "обидно": "обида",
    "жаль": "обида",
    "спасибо": "благодарность",
    "благодарю": "благодарность",
}
_EMOTION_LEMMAS = frozenset(_EMOTION_LEXICON)

_UNCERTAINTY_WORDS = frozenset(
    {
        "наверное",
        "возможно",
        "кажется",
        "вроде",
        "похоже",
        "вероятно",
        "пожалуй",
        "думаю",
        "полагаю",
        "наверно",
    }
)

_ATTRIBUTION_LEMMAS = frozenset(
    {
        "сказать",
        "говорить",
        "ответить",
        "спросить",
        "написать",
        "сообщить",
        "заявить",
        "пояснить",
        "уточнить",
        "добавить",
        "рассказать",
        "рассказывать",
    }
)

_COPULA_LEMMAS = frozenset(
    {"быть", "являться", "называться", "значить", "представлять"}
)
_CONTAINER_LEMMAS = frozenset({"содержать", "включать", "иметь"})
_PART_LEMMAS = frozenset(
    {"часть", "элемент", "компонент", "деталь", "составляющая"}
)

_DASH_RE = re.compile(r"^(?P<left>.+?)\s+[—–-]\s+(?P<right>.+)$")
_COPULA_RE = re.compile(
    r"^(?P<left>[^,;:]+?)\s+(?:—\s+)?"
    r"(?:это|является|называется|значит)\s+(?P<right>[^,;:]+)$",
    re.IGNORECASE,
)
# «Что такое чёрная дыра?» — вопрос об определении составного термина
# (DEBT-211). «Что такое Москва?» тоже сюда, термин из одного слова.
_DEFINITION_RE = re.compile(
    r"^\s*что\s+такое\s+(?P<term>[^?!.]+?)\s*[?!.]?\s*$",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[А-Яа-яЁёA-Za-z]+(?:-[А-Яа-яЁёA-Za-z]+)?")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")
_TERMINAL_RE = re.compile(r"[\s.!?…\"'»)]+$")

# «Нет, …» / «Не, …» в начале реплики — маркер коррекции, а не отрицание
# всего утверждения (DEBT-209). Запятая после «нет» тоже допустима.
_NEGATION_RE = re.compile(
    r"(?<![А-Яа-яЁёA-Za-z])(?:не|нет|ни)(?![А-Яа-яЁёA-Za-z])",
    re.IGNORECASE,
)
_CORRECTION_RE = re.compile(
    r"^\s*(?:нет|не)\s*[,:;—–-]\s*\S", re.IGNORECASE
)

# Местоимения и притяжательные формы первого лица → узел «пользователь».
_FIRST_PERSON_FORMS = frozenset(
    {
        "я",
        "меня",
        "мне",
        "мной",
        "мною",
        "мой",
        "моя",
        "моё",
        "мое",
        "мои",
        "моих",
        "моим",
        "моими",
        "моей",
        "моем",
        "моём",
        "наш",
        "наша",
        "наше",
        "наши",
    }
)
_NAME_VERBS = frozenset({"звать", "называть", "называться"})

_PROPERTY_POS = frozenset({"ADJF", "ADJS", "COMP", "PRTF", "PRTS"})


def _strip_terminal(text: str) -> str:
    return _TERMINAL_RE.sub("", text.strip())


def _split_sentences(text: str) -> tuple[str, ...]:
    parts = [part.strip() for part in _SENTENCE_SPLIT_RE.split(text.strip())]
    return tuple(part for part in parts if part)


def _has_negation(sentence: str) -> bool:
    return bool(_NEGATION_RE.search(" " + sentence + " "))


class PerceptionParser:
    """Главный парсер v0.1: три выхода ADR-002."""

    def __init__(
        self,
        config: Config | None = None,
        *,
        morph: Morphology | None = None,
        syntax: DependencyParser | None = None,
    ) -> None:
        self.config = config or load_config()
        self.morph = morph or Morphology()

        if syntax is not None:
            self.syntax = syntax
        elif self.config.perception.use_syntax:
            model_path = Path(self.config.perception.udpipe_model)
            if not model_path.is_absolute():
                model_path = PROJECT_ROOT / model_path
            self.syntax = (
                DependencyParser(str(model_path)) if model_path.exists() else None
            )
        else:
            self.syntax = None

    # --- публичный вход ------------------------------------------------

    def parse(self, text: str) -> ParseResult:
        normalized = " ".join(text.replace("\u00a0", " ").split())
        if not normalized:
            return ParseResult(text=text, markers=Markers(speech_act=SpeechAct.UNKNOWN))

        sentences = _split_sentences(normalized)
        markers = self._build_markers(normalized, sentences)

        mentions: list[Mention] = []
        statements: list[Statement] = []

        for sentence in sentences:
            is_question = sentence.rstrip().endswith("?")

            # Связка через тире обрабатывается до синтаксиса: это структура
            # «X — это Y», «X — часть Y», «X — зелёная».
            dash_mentions, dash_statements = self._parse_dash(
                sentence, markers, is_question
            )
            if dash_statements:
                mentions.extend(dash_mentions)
                statements.extend(dash_statements)
                continue

            tree = self.syntax.parse(sentence) if self.syntax is not None else None
            if tree is None:
                sentence_mentions, sentence_statements = self._parse_heuristic(
                    sentence, markers, is_question
                )
            else:
                sentence_mentions, sentence_statements = self._parse_tree(
                    sentence, tree, markers, is_question
                )

            copula_mentions, copula_statements = self._parse_copula(
                sentence, markers, is_question
            )
            mentions.extend(sentence_mentions)
            mentions.extend(copula_mentions)
            statements.extend(sentence_statements)
            statements.extend(copula_statements)

            # «Что такое чёрная дыра?» — термин из прилагательного и
            # существительного ищем как единый концепт (DEBT-211).
            term = self._definition_term(sentence)
            if term is not None:
                mentions.append(term)

        return ParseResult(
            text=normalized,
            nodes=tuple(self._dedupe_mentions(mentions)),
            statements=tuple(self._dedupe_statements(statements)),
            markers=markers,
            sentences=sentences,
        )

    # --- маркеры -------------------------------------------------------

    def _build_markers(
        self, text: str, sentences: tuple[str, ...]
    ) -> Markers:
        lowered = normalize_word(text)
        words = _WORD_RE.findall(lowered)

        greeting = self._detect_greeting(sentences)
        is_question = "?" in text
        question_word = next(
            (word for word in words if word in _QUESTION_WORDS), None
        )

        emotion = None
        for word in words:
            label = _EMOTION_LEXICON.get(word)
            if label is None:
                label = _EMOTION_LEXICON.get(self.morph.normal_form(word))
            if label is not None:
                emotion = label
                break

        attribution = self._detect_attribution(sentences)
        modality = next((w for w in words if w in _UNCERTAINTY_WORDS), None)
        has_negation = _has_negation(text)
        correction = any(_CORRECTION_RE.match(sentence) for sentence in sentences)
        definition = any(
            _DEFINITION_RE.match(sentence) for sentence in sentences
        )

        if greeting is not None:
            speech_act = SpeechAct.GREETING
        elif is_question:
            speech_act = SpeechAct.QUESTION
        elif emotion is not None:
            speech_act = SpeechAct.EMOTION
        elif self._is_command(sentences):
            speech_act = SpeechAct.COMMAND
        elif words:
            speech_act = SpeechAct.STATEMENT
        else:
            speech_act = SpeechAct.UNKNOWN

        return Markers(
            speech_act=speech_act,
            is_question=is_question,
            has_negation=has_negation,
            emotion=emotion,
            attribution=attribution,
            question_word=question_word,
            greeting=greeting,
            modality=modality,
            correction=correction,
            definition=definition,
        )

    def _detect_greeting(self, sentences: tuple[str, ...]) -> str | None:
        if not sentences:
            return None
        first = normalize_word(sentences[0])
        for greeting in _GREETINGS:
            if re.match(rf"^{re.escape(greeting)}\b", first):
                return greeting
        return None

    def _detect_attribution(self, sentences: tuple[str, ...]) -> str | None:
        for sentence in sentences:
            words = _WORD_RE.findall(sentence)
            for index, word in enumerate(words[:-1]):
                if self.morph.normal_form(word) in _ATTRIBUTION_LEMMAS:
                    for candidate in reversed(words[:index]):
                        if self.morph.pos(candidate) == "NOUN":
                            return candidate
                    break
        return None

    def _is_command(self, sentences: tuple[str, ...]) -> bool:
        if not sentences:
            return False
        first_word = _WORD_RE.findall(sentences[0])
        if not first_word:
            return False
        return self.morph.is_imperative(first_word[0])

    # --- построение утверждений ---------------------------------------

    def _polarity(
        self, negated: bool, markers: Markers, sentence: str
    ) -> Polarity:
        if negated:
            return Polarity.NEGATED
        words = set(_WORD_RE.findall(normalize_word(sentence)))
        if words & _UNCERTAINTY_WORDS:
            return Polarity.UNSURE
        return Polarity.ASSERTED

    def _sentence_polarity(
        self, sentence: str, markers: Markers
    ) -> Polarity:
        """Отрицание, но не «Нет, …» — это коррекция, а не отказ от факта."""
        correction = bool(_CORRECTION_RE.match(sentence.strip()))
        return self._polarity(
            _has_negation(sentence) and not correction,
            markers,
            sentence,
        )

    @staticmethod
    def _adjective_negated(adjective, markers: Markers) -> bool:
        """«Нет, яблоко сухое» — коррекция, а не «яблоко не сухое».

        UDPipe может прицепить вводное «Нет» к прилагательному-сказуемому.
        Если из отрицающих частиц есть только «нет», это маркер коррекции.
        """
        if not adjective.negated:
            return False
        if not markers.correction:
            return True
        negating = {
            child.form.lower()
            for child in adjective.children
            if child.form.lower() in {"не", "нет", "ни"}
        }
        return bool(negating & {"не", "ни"})

    def _confidence(
        self, polarity: Polarity, is_question: bool
    ) -> float:
        if is_question:
            return 0.3
        if polarity is Polarity.NEGATED:
            return 0.35
        if polarity is Polarity.UNSURE:
            return 0.4
        return 0.55

    def _statement(
        self,
        subject: Mention,
        relation: RelationType,
        obj: Mention,
        label: str,
        *,
        polarity: Polarity,
        is_question: bool,
        sentence: str,
    ) -> Statement:
        return Statement(
            subject=subject,
            relation=relation,
            object=obj,
            label=label,
            polarity=polarity,
            confidence=self._confidence(polarity, is_question),
            is_question=is_question,
            source_text=sentence,
            metadata={"parser": "udpipe" if self.syntax else "heuristic"},
            correction=bool(_CORRECTION_RE.match(sentence.strip())),
        )

    def _verb_relation(
        self, lemma: str, preposition: str | None
    ) -> tuple[RelationType, str, bool]:
        """Возвращает (тип, метка, менять_ли_местами).

        ``менять_ли_местами``: true для «Y состоит из X» / «Y содержит X»,
        где частью является объект, а не субъект.
        """
        if lemma in _COPULA_LEMMAS:
            return RelationType.IS_A, "это", False
        if lemma == "состоять" and preposition == "из":
            return RelationType.PART_OF, "часть", True
        if lemma in _CONTAINER_LEMMAS:
            return RelationType.PART_OF, "часть", True
        if lemma == "входить" and preposition == "в":
            return RelationType.PART_OF, "часть", False
        if preposition:
            return RelationType.RELATED_TO, f"{lemma}_{preposition}", False
        return RelationType.RELATED_TO, lemma, False

    # --- личные факты и местоимения (DEBT-207) ------------------------

    @staticmethod
    def _is_first_person(token: SyntaxToken) -> bool:
        # UDPipe тегирует «мой» то как PRON, то как DET, поэтому форму
        # проверяем до части речи.
        if normalize_word(token.form) in _FIRST_PERSON_FORMS:
            return True
        if not token.is_pronoun:
            return False
        return token.feats.get("Person") == "1"

    def _is_first_person_word(self, word: str) -> bool:
        if normalize_word(word) in _FIRST_PERSON_FORMS:
            return True
        return (
            self.morph.is_pronoun(word)
            and self.morph.feature(word, "person") == "1per"
        )

    @staticmethod
    def _user_mention() -> Mention:
        return Mention(
            lemma=USER_LEMMA,
            form="я",
            pos="PRON",
            node_type=NodeType.CONCEPT,
            features={"person": "1"},
        )

    @staticmethod
    def _open_mention(question_word: str | None) -> Mention:
        """Заполнитель для вопроса, где искомый объект не назван."""
        form = question_word or "что"
        return Mention(
            lemma=form,
            form=form,
            pos="PRON",
            node_type=NodeType.CONCEPT,
            features={"open_question": "true"},
        )

    def _subject_mention(self, token: SyntaxToken | None) -> Mention | None:
        if token is None:
            return None
        if self._is_first_person(token):
            return self._user_mention()
        if token.is_pronoun:
            return None
        mention = self._mention(token)
        if mention is None or not mention.is_concept:
            return None
        return mention

    def _name_statement(
        self,
        verb: SyntaxToken,
        tree: SyntaxTree,
        markers: Markers,
        is_question: bool,
        sentence: str,
        polarity: Polarity,
    ) -> tuple[Statement | None, bool]:
        """«Меня зовут Саша» → пользователь -[имя]-> Саша.

        Возвращает ``(statement, handled)``. ``handled=True`` значит, что
        глагол уже разобран и обычные правила к нему применять не нужно.
        """
        lemma = self.morph.normal_form(verb.form)
        if lemma not in _NAME_VERBS:
            return None, False

        # «Меня» — местоимение, поэтому objects_of (только существительные)
        # его не видит; смотрим всех детей глагола.
        first_person = next(
            (
                token
                for token in verb.children
                if self._is_first_person(token)
            ),
            None,
        )
        if first_person is None:
            return None, False

        user = self._user_mention()
        subject_token = tree.subject_of(verb)
        if subject_token is not None and self._is_first_person(subject_token):
            subject_token = None
        name = self._mention(subject_token) if subject_token else None
        if name is not None and not name.is_concept:
            name = None

        if name is None:
            if not is_question:
                return None, True
            name = self._open_mention(markers.question_word or "что")

        statement = self._statement(
            user,
            RelationType.RELATED_TO,
            name,
            USER_NAME_LABEL,
            polarity=polarity,
            is_question=is_question,
            sentence=sentence,
        )
        return statement, True

    # --- разбор по дереву UDPipe ---------------------------------------

    def _parse_tree(
        self,
        sentence: str,
        tree: SyntaxTree,
        markers: Markers,
        is_question: bool,
    ) -> tuple[list[Mention], list[Statement]]:
        mentions = [
            mention
            for token in tree.tokens
            if (mention := self._mention(token))
        ]
        if any(self._is_first_person(token) for token in tree.tokens):
            mentions.append(self._user_mention())

        polarity = self._sentence_polarity(sentence, markers)
        statements: list[Statement] = []

        # 1. Глагольные рёбра: субъект → глагол(+предлог) → объект.
        for verb in tree.verbs:
            lemma = self.morph.normal_form(verb.form)
            if verb.upos == "AUX":
                continue

            # «Вася сказал, что ...» — глагол речи с придаточным:
            # сам по себе он не факт, придаточное разберётся отдельно.
            if lemma in _ATTRIBUTION_LEMMAS and any(
                child.deprel == "ccomp" for child in verb.children
            ):
                continue

            # «Меня зовут Саша» / «Как меня зовут?» — отдельная связка
            # «пользователь -[имя]-> Саша» (DEBT-207).
            name_statement, handled = self._name_statement(
                verb, tree, markers, is_question, sentence, polarity
            )
            if handled:
                if name_statement is not None:
                    statements.append(name_statement)
                continue

            subject = self._subject_mention(tree.subject_of(verb))
            if subject is None:
                continue

            object_tokens = [
                (token, token.preposition)
                for token in tree.objects_of(verb)
            ]
            object_tokens += [
                (token, token.preposition)
                for token in tree.prepositional_objects_of(verb)
            ]

            usable_objects = [
                (token, preposition)
                for token, preposition in object_tokens
                if self._mention(token) is not None
            ]

            if usable_objects:
                for object_token, preposition in usable_objects:
                    obj = self._mention(object_token)
                    if obj is None:
                        continue
                    relation, label, swap = self._verb_relation(
                        lemma, preposition
                    )
                    statements.append(
                        self._statement(
                            obj if swap else subject,
                            relation,
                            subject if swap else obj,
                            label,
                            polarity=polarity,
                            is_question=is_question,
                            sentence=sentence,
                        )
                    )
            elif is_question and markers.question_word is not None:
                # «Что я люблю?», «Где я живу?» — объект ещё не назван.
                relation, label, swap = self._verb_relation(lemma, None)
                obj = self._open_mention(markers.question_word)
                statements.append(
                    self._statement(
                        obj if swap else subject,
                        relation,
                        subject if swap else obj,
                        label,
                        polarity=polarity,
                        is_question=True,
                        sentence=sentence,
                    )
                )

        # 2. Свойства: прилагательное-сказуемое при существительном.
        #    Прилагательное-определение (amod) в вопросе «Что такое …?»
        #    или в связке «Чёрная дыра — это объект» — часть термина, а не
        #    факт «дыра чёрная» (DEBT-211).
        definition_question = is_question and markers.definition
        has_copula = any(
            token.deprel == "cop"
            or token.form.lower() in {"это", "является"}
            for token in tree.tokens
        )
        for adjective in tree.adjectives:
            if definition_question:
                continue
            if adjective.deprel == "amod" and has_copula:
                continue
            subject_token = tree.subject_of(adjective)
            if subject_token is None:
                head = tree.token(adjective.head)
                if head is not None and head.is_noun:
                    subject_token = head
            subject = self._subject_mention(subject_token)
            obj = self._mention(adjective)
            if subject is None or obj is None:
                continue

            adjective_polarity = (
                Polarity.NEGATED
                if self._adjective_negated(adjective, markers)
                else polarity
            )
            statements.append(
                self._statement(
                    subject,
                    RelationType.HAS_PROPERTY,
                    obj,
                    "свойство",
                    polarity=adjective_polarity,
                    is_question=is_question,
                    sentence=sentence,
                )
            )

        # 3. Именное сказуемое: «Трава это растение», в т.ч. в придаточном
        #    «Вася сказал, что трава это растение».
        for noun in tree.nouns:
            subject_token = tree.subject_of(noun)
            if subject_token is None or not subject_token.is_noun:
                continue

            has_copula = any(
                child.deprel == "cop" for child in noun.children
            ) or self._has_demonstrative_copula(tree, subject_token, noun)
            if not has_copula:
                continue

            subject = self._mention(subject_token)
            obj = self._mention(noun)
            if subject is None or obj is None:
                continue
            statements.append(
                self._statement(
                    subject,
                    RelationType.IS_A,
                    obj,
                    "это",
                    polarity=polarity,
                    is_question=is_question,
                    sentence=sentence,
                )
            )

        return mentions, statements

    @staticmethod
    def _has_demonstrative_copula(
        tree: SyntaxTree, subject: SyntaxToken, noun: SyntaxToken
    ) -> bool:
        """«это» между подлежащим и именной частью = связка."""
        low = min(subject.id, noun.id)
        high = max(subject.id, noun.id)
        for token in tree.tokens:
            if low <= token.id <= high and token.form.lower() in {
                "это",
                "этот",
            }:
                return True
        return False

    # --- связки через тире --------------------------------------------

    def _parse_dash(
        self,
        sentence: str,
        markers: Markers,
        is_question: bool,
    ) -> tuple[list[Mention], list[Statement]]:
        body = _strip_terminal(sentence)
        match = _DASH_RE.match(body)
        if match is None:
            return [], []

        left = self._merge_terms(self._phrase_mentions(match.group("left")))
        right = self._phrase_mentions(match.group("right"))
        subject = next((item for item in left if item.is_concept), None)
        if subject is None or not right:
            return left + right, []

        polarity = self._sentence_polarity(body, markers)
        statements: list[Statement] = []

        if any(item.lemma in _PART_LEMMAS for item in right):
            whole = [
                item
                for item in right
                if item.is_concept and item.lemma not in _PART_LEMMAS
            ]
            if whole:
                statements.append(
                    self._statement(
                        subject,
                        RelationType.PART_OF,
                        whole[-1],
                        "часть",
                        polarity=polarity,
                        is_question=is_question,
                        sentence=sentence,
                    )
                )
        else:
            obj = next((item for item in right if item.is_concept), None)
            prop = next((item for item in right if item.is_property), None)
            if obj is not None:
                statements.append(
                    self._statement(
                        subject,
                        RelationType.IS_A,
                        obj,
                        "это",
                        polarity=polarity,
                        is_question=is_question,
                        sentence=sentence,
                    )
                )
            elif prop is not None:
                statements.append(
                    self._statement(
                        subject,
                        RelationType.HAS_PROPERTY,
                        prop,
                        "свойство",
                        polarity=polarity,
                        is_question=is_question,
                        sentence=sentence,
                    )
                )

        return left + right, statements

    # --- именное сказуемое без тире -----------------------------------

    def _parse_copula(
        self,
        sentence: str,
        markers: Markers,
        is_question: bool,
    ) -> tuple[list[Mention], list[Statement]]:
        """«X это Y» / «X является Y» — структура, а не список слов.

        Требуем ровно один концепт слева и отсутствие глагола: иначе это
        сложное предложение, и им занимается синтаксис.
        """
        match = _COPULA_RE.match(_strip_terminal(sentence))
        if match is None:
            return [], []

        left_words = _WORD_RE.findall(match.group("left"))
        if any(
            self.morph.pos(word) in {"VERB", "INFN"} for word in left_words
        ):
            return [], []

        left = self._merge_terms(self._phrase_mentions(match.group("left")))
        right = self._phrase_mentions(match.group("right"))
        subjects = [item for item in left if item.is_concept]
        if len(subjects) != 1 or not right:
            return left + right, []

        polarity = self._sentence_polarity(sentence, markers)
        if any(item.lemma in _PART_LEMMAS for item in right):
            whole = [
                item
                for item in right
                if item.is_concept and item.lemma not in _PART_LEMMAS
            ]
            if not whole:
                return left + right, []
            statement = self._statement(
                subjects[0],
                RelationType.PART_OF,
                whole[-1],
                "часть",
                polarity=polarity,
                is_question=is_question,
                sentence=sentence,
            )
        else:
            obj = next((item for item in right if item.is_concept), None)
            prop = next((item for item in right if item.is_property), None)
            if obj is not None:
                statement = self._statement(
                    subjects[0],
                    RelationType.IS_A,
                    obj,
                    "это",
                    polarity=polarity,
                    is_question=is_question,
                    sentence=sentence,
                )
            elif prop is not None:
                statement = self._statement(
                    subjects[0],
                    RelationType.HAS_PROPERTY,
                    prop,
                    "свойство",
                    polarity=polarity,
                    is_question=is_question,
                    sentence=sentence,
                )
            else:
                return left + right, []

        return left + right, [statement]

    # --- эвристический fallback (UDPipe недоступен) --------------------

    def _parse_heuristic(
        self,
        sentence: str,
        markers: Markers,
        is_question: bool,
    ) -> tuple[list[Mention], list[Statement]]:
        words = _WORD_RE.findall(sentence)
        mentions = [
            item
            for word in words
            if (item := self._mention_from_form(word)) is not None
        ]
        first_person = any(
            self._is_first_person_word(word) for word in words
        )
        if first_person:
            mentions.append(self._user_mention())

        polarity = self._sentence_polarity(sentence, markers)
        statements: list[Statement] = []

        analyzed: list[tuple[str, str | None, Mention | None]] = []
        for word in words:
            pos = self.morph.pos(word)
            analyzed.append((word, pos, self._mention_from_form(word)))

        # «Что такое …?» — вопрос об определении, а не проверка свойства
        # (DEBT-211): прилагательное входит в термин.
        if is_question and markers.definition:
            return mentions, []

        verb_index = next(
            (i for i, (_, pos, _) in enumerate(analyzed) if pos in {"VERB", "INFN"}),
            None,
        )

        if verb_index is not None:
            word, _, _ = analyzed[verb_index]
            lemma = self.morph.normal_form(word)

            if lemma in _NAME_VERBS and first_person:
                name_mentions = [
                    mention
                    for index, (_, pos, mention) in enumerate(analyzed)
                    if index != verb_index
                    and pos == "NOUN"
                    and mention is not None
                ]
                if name_mentions:
                    obj = name_mentions[-1]
                elif is_question and markers.question_word is not None:
                    obj = self._open_mention(markers.question_word)
                else:
                    obj = None
                if obj is not None:
                    statements.append(
                        self._statement(
                            self._user_mention(),
                            RelationType.RELATED_TO,
                            obj,
                            USER_NAME_LABEL,
                            polarity=polarity,
                            is_question=is_question,
                            sentence=sentence,
                        )
                    )
                return mentions, statements

            subject = next(
                (
                    mention
                    for _, pos, mention in reversed(analyzed[:verb_index])
                    if pos == "NOUN" and mention is not None
                ),
                None,
            )
            if subject is None and any(
                self._is_first_person_word(analyzed[i][0])
                for i in range(verb_index)
            ):
                subject = self._user_mention()

            object_items = [
                (i, mention)
                for i, (_, pos, mention) in enumerate(analyzed)
                if i > verb_index and pos == "NOUN" and mention is not None
            ]
            if subject is not None:
                if object_items:
                    for index, obj in object_items:
                        preposition = None
                        if index > 0 and self.morph.is_preposition(
                            analyzed[index - 1][0]
                        ):
                            preposition = normalize_word(
                                analyzed[index - 1][0]
                            )
                        relation, label, swap = self._verb_relation(
                            lemma, preposition
                        )
                        statements.append(
                            self._statement(
                                obj if swap else subject,
                                relation,
                                subject if swap else obj,
                                label,
                                polarity=polarity,
                                is_question=is_question,
                                sentence=sentence,
                            )
                        )
                        break
                elif is_question and markers.question_word is not None:
                    relation, label, swap = self._verb_relation(lemma, None)
                    obj = self._open_mention(markers.question_word)
                    statements.append(
                        self._statement(
                            obj if swap else subject,
                            relation,
                            subject if swap else obj,
                            label,
                            polarity=polarity,
                            is_question=True,
                            sentence=sentence,
                        )
                    )
        else:
            # Именное сказуемое: «X это Y», «X является Y».
            concepts = [
                mention
                for _, pos, mention in analyzed
                if pos == "NOUN" and mention is not None
            ]
            has_copula = any(
                normalize_word(word) in {"это", "является", "есть", "называется"}
                for word in words
            )
            if has_copula and len(concepts) >= 2:
                statements.append(
                    self._statement(
                        concepts[0],
                        RelationType.IS_A,
                        concepts[-1],
                        "это",
                        polarity=polarity,
                        is_question=is_question,
                        sentence=sentence,
                    )
                )

            properties = [
                mention
                for _, pos, mention in analyzed
                if pos in _PROPERTY_POS and mention is not None
            ]
            if concepts and properties:
                statements.append(
                    self._statement(
                        concepts[0],
                        RelationType.HAS_PROPERTY,
                        properties[0],
                        "свойство",
                        polarity=polarity,
                        is_question=is_question,
                        sentence=sentence,
                    )
                )
            elif first_person and properties:
                statements.append(
                    self._statement(
                        self._user_mention(),
                        RelationType.HAS_PROPERTY,
                        properties[0],
                        "свойство",
                        polarity=polarity,
                        is_question=is_question,
                        sentence=sentence,
                    )
                )

        return mentions, statements

    # --- упоминания ----------------------------------------------------

    def _mention(self, token: SyntaxToken) -> Mention | None:
        if token.is_noun:
            return self._concept(token.form, token.upos, token.feats)
        if token.is_adjective:
            return self._property(token.form, token.upos, token.feats)
        return None

    def _phrase_mentions(self, phrase: str) -> list[Mention]:
        result: list[Mention] = []
        for word in _WORD_RE.findall(phrase):
            item = self._mention_from_form(word)
            if item is not None:
                result.append(item)
        return result

    def _merge_terms(self, mentions: list[Mention]) -> list[Mention]:
        """Склеивает «прилагательное + существительное» в один концепт.

        «чёрная дыра» — это термин, а не свойство «дыра чёрная»
        (DEBT-211). Слияние делается только для имени/подлежащего, не для
        именной части сказуемого.
        """
        merged: list[Mention] = []
        adjectives: list[Mention] = []
        for mention in mentions:
            if mention.is_property:
                adjectives.append(mention)
                continue
            if mention.is_concept and adjectives:
                gender = self.morph.gender(mention.lemma)
                adjective_lemmas = [
                    normalize_word(
                        self.morph.inflect_adjective(
                            item.lemma,
                            case="nominative",
                            gender=gender,
                        )
                    )
                    for item in adjectives
                ]
                merged.append(
                    Mention(
                        lemma=" ".join(adjective_lemmas + [mention.lemma]),
                        form=" ".join(
                            [item.form for item in adjectives]
                            + [mention.form]
                        ),
                        pos="NOUN",
                        node_type=NodeType.CONCEPT,
                        features=dict(mention.features),
                    )
                )
                adjectives = []
                continue
            if adjectives:
                merged.extend(adjectives)
                adjectives = []
            merged.append(mention)
        merged.extend(adjectives)
        return merged

    def _definition_term(self, sentence: str) -> Mention | None:
        """Составной термин из вопроса «Что такое …?» (DEBT-211)."""
        match = _DEFINITION_RE.match(sentence.strip())
        if match is None:
            return None
        words = _WORD_RE.findall(match.group("term"))
        if len(words) < 2:
            return None
        merged = self._merge_terms(
            self._phrase_mentions(match.group("term"))
        )
        return next(
            (
                item
                for item in merged
                if item.is_concept and " " in item.lemma
            ),
            None,
        )

    def _mention_from_form(
        self, form: str, pos: str | None = None
    ) -> Mention | None:
        pos = pos or self.morph.pos(form)
        if pos == "NOUN":
            return self._concept(form, pos, {})
        if pos in _PROPERTY_POS:
            return self._property(form, pos, {})
        return None

    def _concept(
        self, form: str, pos: str, features: dict[str, str]
    ) -> Mention | None:
        lemma = self.morph.normal_form(form)
        if not self._is_node_word(lemma):
            return None
        return Mention(
            lemma=lemma,
            form=form,
            pos=pos,
            node_type=NodeType.CONCEPT,
            features=dict(features),
        )

    def _property(
        self, form: str, pos: str, features: dict[str, str]
    ) -> Mention | None:
        lemma = self.morph.normal_form(form)
        if not self._is_node_word(lemma):
            return None
        return Mention(
            lemma=lemma,
            form=form,
            pos=pos,
            node_type=NodeType.PROPERTY,
            features=dict(features),
        )

    def _is_node_word(self, lemma: str) -> bool:
        if len(lemma) < 2:
            return False
        if lemma in _GREETING_LEMMAS or lemma in _EMOTION_LEMMAS:
            return False
        if lemma in _QUESTION_WORDS or lemma in _UNCERTAINTY_WORDS:
            return False
        if lemma in {"это", "этот", "который", "весь", "свой", "мой", "твой"}:
            return False
        return True

    # --- дедупликация --------------------------------------------------

    def _dedupe_mentions(self, mentions: list[Mention]) -> list[Mention]:
        seen: dict[tuple[str, NodeType], Mention] = {}
        for mention in mentions:
            # «часть» — служебное слово отношения, не самостоятельный концепт.
            if mention.lemma in _PART_LEMMAS:
                continue
            key = (mention.lemma.casefold(), mention.node_type)
            seen.setdefault(key, mention)
        return list(seen.values())

    def _dedupe_statements(
        self, statements: list[Statement]
    ) -> list[Statement]:
        seen: dict[tuple[str, RelationType, str, str], Statement] = {}
        for statement in statements:
            key = (
                statement.subject.lemma.casefold(),
                statement.relation,
                statement.object.lemma.casefold(),
                statement.label,
            )
            seen.setdefault(key, statement)
        return list(seen.values())
