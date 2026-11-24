"""Kannada-English and Tamil-English spelling variants for the normaliser.

Each table maps a loose key (in that language's key) to its canonical key. Textbook spellings
for now; live runs add observed ones. The rule of the Hinglish table holds: never merge two
common distinct words (ಸಾರಿ, sorry, stays apart from ಸರಿ, right; போன், phone, from pon, gold).
"""

KANNADA_VARIANTS: dict[str, str] = {
    "rav": "rao",  # ರಾವ್
    "dr": "doktor",  # Dr.
    "bye": "bai",  # ಬೈ
    "bay": "bai",  # ಬಾಯ್
    "halo": "helo",  # ಹಲೋ, hello
    "okay": "oke",  # ಓಕೆ
    "ok": "oke",
    "you": "yu",  # ಯೂ
    "taim": "time",  # ಟೈಮ್
    "plis": "please",  # ಪ್ಲೀಸ್
    "fone": "fon",  # phone, ಫೋನ್
    "aitu": "aytu",  # ಆಯ್ತು
    "houdu": "haudu",  # ಹೌದು
    "hovdu": "haudu",  # howdu
    "jothege": "jotege",  # ಜೊತೆಗೆ, with ತ written th
    "jothe": "jote",
    "ghante": "gante",  # ಗಂಟೆ
    "ega": "iga",  # ಈಗ, eega
}
TAMIL_VARIANTS: dict[str, str] = {
    "rav": "rao",  # ராவ்
    "tr": "toktor",  # Dr. (ta-en reads dr as tr)
    "pye": "pai",  # bye, பை
    "halo": "helo",  # ஹலோ, hello
    "okay": "oke",  # ஓகே
    "ok": "oke",
    "you": "yu",  # யூ
    "taim": "time",  # டைம்
    "plis": "please",  # ப்ளீஸ்
    "fone": "fon",  # phone, ஃபோன்
    "seri": "sari",  # சரி
    "ilai": "ila",  # இல்லை, illa
    "iniki": "iniku",  # inniki, இன்னிக்கு
    "inaiku": "iniku",  # இன்னைக்கு
    "tamil": "thamijh",  # the English name; தமிழ், thamizh (zh reads jh)
}
