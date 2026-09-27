"""Compte les offres CRÉÉES ET PROUVÉES dans les journaux de production (lecture seule).

Une offre compte quand `logs/<run>.jsonl` porte `submit_offer` avec `success: true` : la saisie
a été prouvée par la disparition de l'offre du feed rafraîchi. Le marchand est lu dans
`approved.json` / `candidates.json` du run (store id), à défaut dans le nom du run.

    python3 compter_creations.py [--base /home/debian/executor]

À lancer sur chaque machine, puis additionner (voir ../chiffres.md). Aucun secret n'est lu."""
import json, glob, os, collections, re, sys
BASE = sys.argv[sys.argv.index('--base') + 1] if '--base' in sys.argv else '/home/debian/executor'
STORE = {'126':'GameSeal','51':'Gamivo','19':'Eneba','58':'Kinguin','38':'G2A','30':'CJS-CDKeys','157':'GameBoost','13':'Gamerall','127':'Driffle','70':'Electronicfirst','28':'Instant Gaming','17':'Allyouplay','12':'MMOGA','92':'K4G','31':'GamersOutlet','167':'Difmark','34':'GOG','162':'Wyrel','55':'Gamesplanet FR','168':'Discover.games','40':'Loaded'}
ALIAS = {'gameseal':'GameSeal','gamivo':'Gamivo','eneba':'Eneba','kinguin':'Kinguin','g2a':'G2A','cjs':'CJS-CDKeys','gameboost':'GameBoost','gamerall':'Gamerall','driffle':'Driffle','electronicfirst':'Electronicfirst','instant':'Instant Gaming','allyouplay':'Allyouplay','mmoga':'MMOGA','k4g':'K4G','gamersoutlet':'GamersOutlet','difmark':'Difmark','dif':'Difmark','gog':'GOG','wyrel':'Wyrel','gamesplanet':'Gamesplanet FR','discover':'Discover.games','loaded':'Loaded'}
def merchant_of(run, oid, cache):
    if run not in cache:
        m = {}
        for name in ('approved.json','candidates.json','validation.json'):
            p = f'{BASE}/runs/{run}/{name}'
            if os.path.exists(p):
                try:
                    d = json.load(open(p))
                    items = d if isinstance(d, list) else (d.get('candidates') or d.get('approved') or [])
                    for c in items:
                        o = c.get('offer') or {}
                        if o.get('offer_id'):
                            m[str(o['offer_id'])] = (o.get('merchant'), str(o.get('store_id') or ''))
                except Exception: pass
                if m: break
        cache[run] = m
    hit = cache[run].get(str(oid))
    if hit:
        return STORE.get(hit[1]) or hit[0] or 'inconnu'
    ms = re.search(r'-s(\d+)(?:-p\d+)?', run)
    if ms and ms.group(1) in STORE: return STORE[ms.group(1)]
    for tok in re.split(r'[-_]', run.lower()):
        if tok in ALIAS: return ALIAS[tok]
    return 'inconnu:' + run
cache = {}; per_m = collections.Counter(); per_day = collections.Counter(); seen=set()
for f in glob.glob(BASE + '/logs/*.jsonl'):
    run = os.path.basename(f)[:-6]
    try:
        for l in open(f, errors='replace'):
            if '"submit_offer"' not in l or '"success": true' not in l: continue
            try: e = json.loads(l)
            except Exception: continue
            if e.get('event') != 'submit_offer' or e.get('success') is not True: continue
            key = (run, e.get('offer_id'), e.get('ts'))
            if key in seen: continue
            seen.add(key)
            per_m[merchant_of(run, e.get('offer_id'), cache)] += 1
            per_day[e.get('ts','')[:10]] += 1
    except Exception: pass
print(json.dumps({'total': sum(per_m.values()), 'per_merchant': per_m.most_common(), 'per_day': sorted(per_day.items())}, ensure_ascii=False))
