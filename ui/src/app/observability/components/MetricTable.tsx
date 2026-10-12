'use client';

import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

export interface Column<Row> {
    header: string;
    /** Cell contents. Returning null renders an em dash. */
    cell: (row: Row) => React.ReactNode;
    align?: 'left' | 'right';
    /** Monospace, for figures that should line up down the column. */
    numeric?: boolean;
}

interface MetricTableProps<Row> {
    title: string;
    description: string;
    columns: Column<Row>[];
    rows: Row[];
    loading?: boolean;
    /** Shown instead of the table when there are no rows. */
    emptyMessage?: string;
}

/**
 * One panel of the telemetry dashboard.
 *
 * Generic over its rows on purpose. Every panel groups by a dimension rather
 * than enumerating a known list, so the rows that arrive depend on what the
 * system actually did: a tool server registered this morning appears here
 * without this component, or the page, knowing anything about it.
 */
export function MetricTable<Row>({
    title,
    description,
    columns,
    rows,
    loading = false,
    emptyMessage = 'No activity recorded in this period.',
}: MetricTableProps<Row>) {
    return (
        <Card className="p-5">
            <h2 className="text-sm font-semibold text-foreground">{title}</h2>
            <p className="mt-1 text-xs text-muted-foreground">{description}</p>

            {loading ? (
                <div className="mt-4 space-y-2">
                    {[0, 1, 2].map((i) => (
                        <Skeleton key={i} className="h-8 w-full" />
                    ))}
                </div>
            ) : rows.length === 0 ? (
                <p className="mt-6 text-sm text-muted-foreground">{emptyMessage}</p>
            ) : (
                <div className="mt-4 overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-border">
                                {columns.map((column) => (
                                    <th
                                        key={column.header}
                                        className={`pb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground ${
                                            column.align === 'right'
                                                ? 'text-right'
                                                : 'text-left'
                                        }`}
                                    >
                                        {column.header}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((row, rowIndex) => (
                                <tr
                                    key={rowIndex}
                                    className="border-b border-border/50 last:border-0"
                                >
                                    {columns.map((column) => (
                                        <td
                                            key={column.header}
                                            className={`py-2 ${
                                                column.align === 'right'
                                                    ? 'text-right'
                                                    : 'text-left'
                                            } ${column.numeric ? 'font-mono tabular-nums' : ''}`}
                                        >
                                            {column.cell(row) ?? '—'}
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </Card>
    );
}
