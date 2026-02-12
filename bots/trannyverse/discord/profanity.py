import json

BAD_WORDS_CRITICAL = [
    # Slurs and hate speech
    'chink','chinks', 'faggot','faggots', 'fag','fags',
    'nigger','niggers','kike','kikes', 'spic', 'wetback','negroid',
    'gook', 'coon', 'dyke','paki','nog','troon','troons',
    # Violence keywords in threatening context
    'kys', 'kill yourself', 'kill urself', 'kill all',
    'death to','should die','rape you',
]

masked_chars = {
	"a": ("a", "@", "*", "4"),
	"i": ("i", "*", "1", "+", "@", "!", "|", "í", "ì", "î", "ï", "ĩ", "ī", "ĭ", "ỉ", "ị", "ḭ", "ɨ", "ᶖ", "ḯ", "ᶃ", "ỉ", '2', '3', '4', '5', '6', '7', '8', '9', '0', '#', 'l'),
	"b": ("b", "8"),
	"g": ("g", "6", "9"),
	"r": ("r", "2"),
	"o": ("o", "*", "0", "@"),
	"u": ("u", "*", "v"),
	"v": ("v", "*", "u"),
	"e": ("e", "*", "3"),
	"s": ("s", "$", "5"),
	"t": ("t", "7"),
	"n": ('ñ', 'ń', 'ǹ', 'ň', 'ņ', 'n̓', 'n‌̧', 'ɲ', 'ŋ', 'ɳ', 'ƞ', 'ȵ', 'ṅ', 'ṇ', 'n̄', 'ṉ', 'ṋ'),
}

masked_char_mapping = {}

for key, values in masked_chars.items():
	for value in values:
		masked_char_mapping[value] = key


def contains_bad_word(string):
	word = string.lower()
	
	# Replace masked characters using the mapping
	for char in word:
		word = word.replace(char, masked_char_mapping.get(char, char))
		# print("Replacing", char, "with", masked_char_mapping.get(char, char))
	
	for bad_word in BAD_WORDS_CRITICAL:
		if bad_word in word:
			return True
	return False


def debug():
	print(contains_bad_word('ni11er'))
	print(contains_bad_word('blgger'))


if __name__ == '__main__':
	debug()
