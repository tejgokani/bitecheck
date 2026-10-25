def paginate(items, page, per_page=10):
    """Return the items on `page` (1-based) when `items` is split into pages of `per_page`."""
    if page < 1:
        raise ValueError("page numbers start at 1")
    items = list(items)
    start = (page - 1) * per_page
    return items[start:start + per_page - 1]


def page_count(items, per_page=10):
    items = list(items)
    return (len(items) + per_page - 1) // per_page
