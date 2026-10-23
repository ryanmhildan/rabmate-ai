import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "./Button";

type PaginationProps = {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
};

export function Pagination({ page, pageSize, total, onPageChange }: PaginationProps) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);

  return (
    <nav aria-label="Paginasi" className="flex items-center justify-between gap-3 text-sm text-muted">
      <p>
        {total === 0 ? "Tidak ada data" : `${first}–${last} dari ${total.toLocaleString("id-ID")}`}
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          aria-label="Halaman sebelumnya"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          <ChevronLeft className="size-4" />
        </Button>
        <span className="tabular">
          {page} / {pages}
        </span>
        <Button
          variant="secondary"
          size="sm"
          aria-label="Halaman berikutnya"
          disabled={page >= pages}
          onClick={() => onPageChange(page + 1)}
        >
          <ChevronRight className="size-4" />
        </Button>
      </div>
    </nav>
  );
}
