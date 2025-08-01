import json
import nltk
import spacy
import skfuzzy as fuzz
import numpy as np
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from typing import Dict, List, Tuple
import os
import re

# Check if vader_lexicon is already downloaded
def ensure_vader_lexicon():
    try:
        nltk.data.find('sentiment/vader_lexicon')
    except LookupError:
        try:
            nltk.download('vader_lexicon')
        except Exception as e:
            raise Exception(f"Failed to download vader_lexicon and it's not locally available: {e}")

# Initialize NLP tools
ensure_vader_lexicon()
sid = SentimentIntensityAnalyzer()
nlp = spacy.load('en_core_web_sm')

def load_serialized_transcription(file_path: str) -> List[Dict]:
    with open(file_path, 'r') as f:
        return json.load(f)

def get_sentiment_score(dialogue: List[Dict]) -> Tuple[str, Dict[str, float], List[str]]:
    customer_text = ' '.join(entry['dialogue'] for entry in dialogue if entry['speaker'] == 'spk2')
    scores = sid.polarity_scores(customer_text)
    keywords = []
    
    sentiment_scores = {
        'Positive': max(0.0, scores['pos']),
        'Neutral': max(0.0, scores['neu']),
        'Negative': max(0.0, scores['neg'])
    }
    
    if sentiment_scores['Positive'] > sentiment_scores['Negative'] and sentiment_scores['Positive'] > 0.2:
        sentiment = 'positive'
        keywords.extend(['positive', 'agree', 'thanks'])
    elif sentiment_scores['Negative'] > sentiment_scores['Positive'] and sentiment_scores['Negative'] > 0.2:
        sentiment = 'negative'
        keywords.extend(['negative', 'issue'])
    else:
        sentiment = 'neutral'
        keywords.append('neutral')
    
    return sentiment, sentiment_scores, list(set(keywords))

def get_cooperation_level(dialogue: List[Dict]) -> Tuple[Dict[str, float], List[str]]:
    cooperation_score = 0.0
    rep_supportive = 0.0
    keywords = []
    for entry in dialogue:
        text = entry['dialogue'].lower()
        if entry['speaker'] == 'spk2':
            if any(phrase in text for phrase in ['i’ll pay', 'sure', 'meaning to clear']):
                cooperation_score += 0.4
                keywords.extend(['i’ll pay', 'sure', 'meaning to clear'])
            if any(phrase in text for phrase in ['no', 'won’t', 'can’t']) and 'pay' in text:
                cooperation_score -= 0.3
                keywords.extend(['no', 'won’t', 'can’t'])
        if entry['speaker'] == 'spk1':
            if any(phrase in text for phrase in ['of course', 'perfect', 'thank you']):
                rep_supportive += 0.2
                keywords.extend(['of course', 'perfect', 'thank you'])
    cooperation_score += rep_supportive * 0.3
    return {
        'High': min(cooperation_score, 0.9),
        'Medium': max(0.1, 1 - cooperation_score),
        'Low': max(0.0, 0.3 - cooperation_score)
    }, list(set(keywords))

def get_resolution_level(dialogue: List[Dict]) -> Tuple[Dict[str, float], List[str]]:
    resolution_score = 0.0
    keywords = []
    for i, entry in enumerate(dialogue):
        text = entry['dialogue'].lower()
        if 'pay' in text and any(word in text for word in ['today', 'evening']):
            resolution_score += 0.5
            keywords.extend(['pay', 'today', 'evening'])
        if any(word in text for word in ['reflects', 'resolved', 'cleared']):
            resolution_score += 0.3
            keywords.extend(['reflects', 'resolved', 'cleared'])
        if i > len(dialogue) / 2:
            resolution_score *= 1.2
    return {
        'High': min(resolution_score, 0.9),
        'Medium': max(0.1, 1 - resolution_score),
        'Low': max(0.0, 0.3 - resolution_score)
    }, list(set(keywords))

def get_entity_score(dialogue: List[Dict]) -> Tuple[Dict[str, float], List[str]]:
    product_scores = {'credit card': 0.05, 'saving account': 0.05, 'insurance': 0.05, 'travel card': 0.05}
    keywords = []
    all_text = ' '.join(entry['dialogue'] for entry in dialogue)
    doc = nlp(all_text.lower())
    
    for token in doc:
        text = token.text
        if text in ['credit', 'card'] or 'card ending' in all_text:
            product_scores['credit card'] += 0.4
            keywords.extend(['credit', 'card', 'card ending'])
        if text in ['savings', 'account']:
            product_scores['saving account'] += 0.4
            keywords.extend(['savings', 'account'])
        if text == 'insurance' or 'policy' in all_text:
            product_scores['insurance'] += 0.4
            keywords.extend(['insurance', 'policy'])
        if 'travel' in text or 'foreign transaction' in all_text:
            product_scores['travel card'] += 0.4
            keywords.extend(['travel', 'foreign transaction'])
    
    for ent in doc.ents:
        if ent.label_ == 'PRODUCT':
            if 'card' in ent.text.lower():
                product_scores['credit card'] += 0.3
                keywords.append(ent.text.lower())
            elif 'account' in ent.text.lower():
                product_scores['saving account'] += 0.3
                keywords.append(ent.text.lower())
            elif 'insurance' in ent.text.lower():
                product_scores['insurance'] += 0.3
                keywords.append(ent.text.lower())
    
    return {k: min(v, 0.95) for k, v in product_scores.items()}, list(set(keywords))

def get_contextual_relevance(dialogue: List[Dict]) -> Tuple[Dict[str, float], List[str]]:
    relevance_scores = {'credit card': 0.05, 'saving account': 0.05, 'insurance': 0.05, 'travel card': 0.05}
    keywords = []
    for entry in dialogue:
        text = entry['dialogue'].lower()
        if 'overdue' in text or 'late fee' in text:
            relevance_scores['credit card'] += 0.4
            keywords.extend(['overdue', 'late fee'])
        if 'balance' in text or 'deposit' in text:
            relevance_scores['saving account'] += 0.4
            keywords.extend(['balance', 'deposit'])
        if 'premium' in text or 'claim' in text:
            relevance_scores['insurance'] += 0.4
            keywords.extend(['premium', 'claim'])
        if 'foreign' in text or 'travel' in text:
            relevance_scores['travel card'] += 0.4
            keywords.extend(['foreign', 'travel'])
    return {k: min(v, 0.9) for k, v in relevance_scores.items()}, list(set(keywords))

def generate_consumables_insights(dialogue: List[Dict], product: str, resolution_level: Dict[str, float]) -> List[str]:
    keywords = []
    
    for entry in dialogue:
        text = entry['dialogue'].lower()
        if 'overdue payment' in text:
            keywords.append('overdue')
            amount_match = re.search(r'₹([\d,]+)', text)
            if amount_match:
                keywords.append(amount_match.group(0))
        if 'late fee' in text:
            keywords.append('late fee')
        if 'i’ll pay' in text or 'pay it online' in text:
            keywords.extend(['pay', 'committed'])
        if 'reflects' in text and 'late fee' in text:
            keywords.append('resolve')
    
    if product:
        keywords.append(product)
    
    if resolution_level['High'] > 0.5:
        keywords.append('high')
    elif resolution_level['Medium'] > 0.5:
        keywords.append('medium')
    else:
        keywords.append('low')
    
    return list(set(keywords)) if keywords else ['no_insights']

def fuzzy_intent(sentiment_scores: Dict, cooperation: Dict, resolution: Dict) -> Tuple[str, float]:
    positive = min(sentiment_scores['Positive'], cooperation['High'], resolution['High'])
    positive += min(sentiment_scores['Neutral'], cooperation['Medium'], resolution['Medium']) * 0.5
    negative = max(sentiment_scores['Negative'], cooperation['Low'], resolution['Low'])
    
    intent_score = positive / (positive + negative + 1e-10)
    intent = 'positive' if intent_score > 0.5 else 'negative'
    confidence = max(positive, negative)
    return intent, confidence

def fuzzy_product(entity_scores: Dict, relevance_scores: Dict) -> Tuple[str, float]:
    product_scores = {}
    for product in entity_scores:
        product_scores[product] = min(entity_scores[product], relevance_scores[product])
    
    selected_product = max(product_scores, key=product_scores.get)
    confidence = product_scores[selected_product]
    return selected_product, confidence

def process_serialized_transcription(serialized_transcription: List[Dict]) -> Dict:
    sentiment, sentiment_scores, sentiment_keywords = get_sentiment_score(serialized_transcription)
    cooperation, cooperation_keywords = get_cooperation_level(serialized_transcription)
    resolution, resolution_keywords = get_resolution_level(serialized_transcription)
    entity_scores, entity_keywords = get_entity_score(serialized_transcription)
    relevance_scores, relevance_keywords = get_contextual_relevance(serialized_transcription)
    
    intent, intent_confidence = fuzzy_intent(sentiment_scores, cooperation, resolution)
    product, _ = fuzzy_product(entity_scores, relevance_scores)
    
    critical_keywords = list(set(
        sentiment_keywords + cooperation_keywords + resolution_keywords +
        entity_keywords + relevance_keywords
    ))
    
    consumables_insights = generate_consumables_insights(serialized_transcription, product, resolution)
    
    return {
        'intent': intent,
        'critical_keywords': critical_keywords,
        'consumables_insights': consumables_insights,
        'confidence': {
            'intent': round(intent_confidence, 2)
        }
    }

if __name__ == "__main__":
    serialized_transcription = load_serialized_transcription('transcription.json')
    result = process_serialized_transcription(serialized_transcription)
    print(json.dumps(result, indent=2))