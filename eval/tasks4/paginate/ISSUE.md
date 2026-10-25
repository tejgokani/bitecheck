`paginate` treats pages as 0-based even though they are documented as 1-based: `paginate(range(10), page=1, per_page=5)`
returns `[5, 6, 7, 8, 9]` instead of `[0, 1, 2, 3, 4]`, and the last page comes back empty. A page number below 1 should
raise `ValueError`.
