'use client';

interface SectionHeadingProps {
    title: string;
    description?: string;
    /** Rendered on the right, e.g. a row count or a control. */
    aside?: React.ReactNode;
}

/**
 * The heading above a group of panels.
 *
 * The dashboard had nine cards in one flat scroll, which is why nothing on it
 * read as structured: every panel claimed the same importance as every other.
 * Grouping them under headings is what turns the page into sections a reader
 * can skip rather than a list they have to read.
 */
export function SectionHeading({ title, description, aside }: SectionHeadingProps) {
    return (
        <div className="flex flex-wrap items-end justify-between gap-2 border-b border-border pb-2">
            <div>
                <h2 className="text-[13px] font-semibold uppercase tracking-wider text-foreground">
                    {title}
                </h2>
                {description && (
                    <p className="mt-1 max-w-2xl text-xs text-muted-foreground">
                        {description}
                    </p>
                )}
            </div>
            {aside && <div className="text-xs text-muted-foreground">{aside}</div>}
        </div>
    );
}
