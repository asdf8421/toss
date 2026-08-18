import { index, integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const analysisSnapshots = sqliteTable(
  "analysis_snapshots",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    runId: text("run_id").notNull().unique(),
    asOfDate: text("as_of_date").notNull(),
    publishedAt: text("published_at").notNull(),
    payloadJson: text("payload_json").notNull(),
    createdAt: text("created_at").notNull(),
  },
  (table) => [index("idx_analysis_snapshots_published_at").on(table.publishedAt)],
);
