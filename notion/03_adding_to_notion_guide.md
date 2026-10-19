# Adding SupplierPulse to the Notion portfolio

Nothing in this folder has been published, and the existing Notion page has not been changed. This guide adds SupplierPulse as the second project without touching the InventoryIQ case study.

**What is ready:** the homepage block (`01_homepage_addition.md`), the case study (`02_supplierpulse_case_study.md`), and four genuine screenshots (`screenshots/`). The homepage reuses the first case-study image, so the project uses four screenshots in total.
**What you still supply:** the three links, after the GitHub repository is published (section 4).

## 1. Homepage

1. Open the published portfolio page in Notion (edit mode).
2. Below the InventoryIQ block, type `/divider`.
3. Add a **Heading 2**: `SupplierPulse — Supplier Performance & Procurement Analytics`.
4. Paste the one-sentence description from `01_homepage_addition.md` as normal text.
5. Drag `screenshots/01-procurement-overview.png` under the description and resize it to the same width as the InventoryIQ image.
6. Leave the GitHub link out until the repository exists. Then add the line `Read the case study · GitHub`, as InventoryIQ has.
7. Decide whether to keep the *"More projects are in progress"* line.

## 2. Case-study page

1. Under the SupplierPulse screenshot on the homepage, type `/page` and name it **SupplierPulse — Supplier Performance & Procurement Analytics**.
2. Paste the text of `02_supplierpulse_case_study.md`. Keep the InventoryIQ section order: Why I built this, Tools I used, What I did, Visual proof, What I learned, What I'd do next, Links.
3. Delete the Markdown image lines, then drag the images in:
   - `01-procurement-overview.png` and `02-supplier-scorecard.png` side by side (two columns);
   - `03-action-list.png` and `04-decision-brief.png` side by side underneath.
4. Click each image → **Caption** → paste the italic caption from the text.
5. Keep the italic note above the images and the small footnote at the bottom. They state which parts are real and which are synthetic.
6. Standard width (not full width), with no emoji, badges or colours other than link blue, to match InventoryIQ.

## 3. Wording rules to keep

- Always say **"observed City of Austin data"** for spend, concentration and price findings.
- Always say **"synthetic"** for scorecard, OTIF and supplier-ID (SUP-xx) results.
- Never describe the price-harmonisation figure as savings; it is a *modelled opportunity*.
- Do not name the fuel vendor on the Notion page. The GitHub analysis names it in context, but naming a real company on a portfolio page invites misreading the finding as a criticism.

## 4. Links to add after publishing

| Link text | Target once the repository is public |
|---|---|
| View GitHub | `https://github.com/harjotsandhu24/supplierpulse-procurement-analytics` |
| Download Excel Analysis | `.../blob/main/deliverables/SupplierPulse_Procurement_Analysis.xlsx` |
| Read the One-Page Decision Brief | `.../blob/main/deliverables/SupplierPulse_Decision_Brief.pdf` |

Replace each `ADD-AFTER-PUBLISHING` placeholder in the case study only after confirming the link opens.
