from speech_analytics import analyze_transcript

conv = {
    'user': [
        {'text': 'um I basically worked on like a system design project you know', 'timestamp': 1.0},
        {'text': 'It was actually really interesting', 'timestamp': 10.0}
    ]
}

r = analyze_transcript(conv)
print('filler_total:', r['filler_total'])
print('filler_breakdown:', r['filler_breakdown'])
print('word_count:', r['word_count'])
print('avg_wpm:', r['avg_words_per_minute'])
print('\nFull result:')
for key, value in r.items():
    print(f'  {key}: {value}')

# Verify filler_total >= 4
assert r['filler_total'] >= 4, f"Expected filler_total >= 4, got {r['filler_total']}"
print('\nVerification PASSED: filler_total >= 4')
