"use client";

type PageItem = number | "ellipsis";

function paginationItems(currentPage: number, totalPages: number): PageItem[] {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  const pages = new Set<number>([1, totalPages, currentPage]);
  if (currentPage > 2) pages.add(currentPage - 1);
  if (currentPage < totalPages - 1) pages.add(currentPage + 1);
  if (currentPage <= 3) {
    pages.add(2);
    pages.add(3);
  }
  if (currentPage >= totalPages - 2) {
    pages.add(totalPages - 2);
    pages.add(totalPages - 1);
  }

  const sortedPages = Array.from(pages)
    .filter((page) => page >= 1 && page <= totalPages)
    .sort((first, second) => first - second);

  const items: PageItem[] = [];
  for (const page of sortedPages) {
    const previous = items[items.length - 1];
    if (typeof previous === "number" && page - previous > 1) {
      items.push("ellipsis");
    }
    items.push(page);
  }
  return items;
}

export function Pagination({
  currentPage,
  disabled = false,
  onPageChange,
  pageSize,
  total,
}: {
  currentPage: number;
  disabled?: boolean;
  onPageChange: (page: number) => void;
  pageSize: number;
  total: number;
}) {
  const totalPages = Math.ceil(total / pageSize);
  if (totalPages <= 1) return null;

  const clampedPage = Math.min(Math.max(currentPage, 1), totalPages);
  const pageStart = (clampedPage - 1) * pageSize + 1;
  const pageEnd = Math.min(clampedPage * pageSize, total);

  return (
    <div className="pagination-bar">
      <button
        className="secondary-button"
        disabled={disabled || clampedPage === 1}
        onClick={() => onPageChange(clampedPage - 1)}
        type="button"
      >
        Назад
      </button>
      <div className="pagination-pages" aria-label="Сторінки заявок">
        {paginationItems(clampedPage, totalPages).map((item, index) =>
          item === "ellipsis" ? (
            <span className="pagination-ellipsis" key={`ellipsis-${index}`}>
              ...
            </span>
          ) : (
            <button
              className={item === clampedPage ? "pagination-page active" : "pagination-page"}
              disabled={disabled}
              key={item}
              onClick={() => onPageChange(item)}
              type="button"
            >
              {item}
            </button>
          ),
        )}
      </div>
      <button
        className="secondary-button"
        disabled={disabled || clampedPage === totalPages}
        onClick={() => onPageChange(clampedPage + 1)}
        type="button"
      >
        Вперед
      </button>
      <span className="muted small">
        {pageStart}-{pageEnd} з {total}
      </span>
    </div>
  );
}
