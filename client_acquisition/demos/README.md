# Demo Projects

Static HTML prototypes demonstrating proposed improvements for specific leads.
Each demo is tied to a lead key and is viewable by opening `index.html` in a browser.

## Demos

| Directory | Lead | Opportunity |
|-----------|------|-------------|
| `garage-avo/` | Garage Avo (Davtashen) | Business website with service listing and booking form |
| `anka-beauty/` | Anka Beauty Salon (Pushkin 33) | Beauty salon website with services and appointment booking |
| `varda-nails/` | Varda Nail Studio (Baghramyan 1) | Nail studio website with price list and portfolio |

## How to run locally

```bash
cd client_acquisition/demos/<demo-name>
python -m http.server 8000
# Open http://localhost:8000
```

All demos use synthetic data and are static HTML/CSS. No external dependencies.
