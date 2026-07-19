# Meteo Italia 24 — Previsioni automatiche per 27 città

Sistema gratuito basato su:

- ECMWF IFS Open Data 0,25°
- GitHub Actions
- GitHub Pages
- Python + ecCodes

## Funzionamento

Il workflow scarica automaticamente i dati ECMWF una volta al giorno,
estrae i valori per 27 città italiane, crea una previsione indicativa
per oggi, domani e dopodomani e aggiorna `docs/data/weather.json`.

Se il download o la validazione non riescono, il file pubblico precedente
non viene sostituito con dati incompleti.

## Licenza e attribuzione

I dati ECMWF Open Data sono distribuiti con licenza CC BY 4.0.
La pagina mostra l'attribuzione richiesta.

Queste previsioni sono indicative e non costituiscono allerte ufficiali.
