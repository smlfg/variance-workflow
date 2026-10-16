# textkit (demo target)

Tiny demo repo for the variance workflow. One feature, `slugify`, with a plugin
registry so several implementations can live side by side:

```python
from textkit.slugify import slugify, available
slugify("Äpfel & Birnen")               # default variant (env TEXTKIT_SLUGIFY or "ref")
slugify("Äpfel & Birnen", variant="a")  # pick one explicitly
sorted(available())                      # ['a', 'b', ..., 'ref']
```

Run the contract tests for one variant: `VW_VARIANT=a PYTHONPATH=src python3 -m unittest discover -s tests/acceptance`
