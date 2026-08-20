import { index, integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const analysisSnapshots = sqliteTable(
  "analysis_snapshots",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    runId: text("run_id").notNull().unique(),
    marketScope: text("market_scope").notNull().default("KR"),
    asOfDate: text("as_of_date").notNull(),
    publishedAt: text("published_at").notNull(),
    payloadJson: text("payload_json").notNull(),
    createdAt: text("created_at").notNull(),
  },
  (table) => [
    index("idx_analysis_snapshots_published_at").on(table.publishedAt),
    index("idx_analysis_snapshots_market_published").on(table.marketScope, table.publishedAt),
  ],
);

export const analysisRequests = sqliteTable(
  "analysis_requests",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    requestId: text("request_id").notNull().unique(),
    marketScope: text("market_scope").notNull().default("KR"),
    status: text("status").notNull(),
    requestedAt: text("requested_at").notNull(),
    previousRunId: text("previous_run_id"),
    completedAt: text("completed_at"),
    completedRunId: text("completed_run_id"),
    failureMessage: text("failure_message"),
  },
  (table) => [
    index("idx_analysis_requests_requested_at").on(table.requestedAt),
    index("idx_analysis_requests_market_requested").on(table.marketScope, table.requestedAt),
  ],
);
