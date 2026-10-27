// Mirrors the backend response schemas (services/api/app/modules/*/schemas.py).
// Money, rates and quantities are decimal strings: never parse them into numbers for math.

export type Permission =
  | "org.read"
  | "org.update"
  | "users.read"
  | "users.manage"
  | "audit.read"
  | "clients.read"
  | "clients.write"
  | "clients.delete"
  | "projects.read"
  | "projects.write"
  | "projects.delete"
  | "rab.read"
  | "rab.write"
  | "rab.approve"
  | "pricing.read"
  | "pricing.write"
  | "pricing.verify"
  | "documents.read"
  | "documents.issue"
  | "documents.approve"
  | "finance.read"
  | "finance.write"
  | "ai.use";

export type Role = "owner" | "project_manager" | "estimator" | "finance" | "approver" | "viewer";

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

export type UserBrief = { id: string; email: string; full_name: string };
export type OrganizationBrief = { id: string; name: string };

export type Me = {
  user: UserBrief;
  organization: OrganizationBrief;
  role: Role;
  role_label: string;
  permissions: Permission[];
  organizations: (OrganizationBrief & { role: Role })[];
};

export type Organization = {
  id: string;
  name: string;
  legal_name: string | null;
  tax_id: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  city: string | null;
  website: string | null;
  updated_at: string;
};

export type Member = {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  role_label: string;
  is_active: boolean;
  last_login_at: string | null;
  joined_at: string;
};

export type RoleInfo = { role: Role; label: string; permissions: Permission[] };

export type ClientType = "company" | "individual" | "government" | "other";

export type Client = {
  id: string;
  code: string | null;
  name: string;
  client_type: ClientType;
  tax_id: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  city: string | null;
  contact_person: string | null;
  notes: string | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
};

export type ClientBrief = { id: string; code: string | null; name: string };

export type ProjectType =
  | "construction"
  | "fabrication"
  | "procurement"
  | "it"
  | "professional_services"
  | "operations"
  | "other";

export type ProjectStatus = "prospect" | "active" | "on_hold" | "completed" | "cancelled";

export type ProjectListItem = {
  id: string;
  number: string;
  name: string;
  project_type: ProjectType;
  status: ProjectStatus;
  client: ClientBrief | null;
  start_date: string | null;
  end_date: string | null;
  currency: string;
  budget_amount: string | null;
  updated_at: string;
};

export type AttributeValue = string | number | boolean | null;

export type Project = ProjectListItem & {
  description: string | null;
  scope: string | null;
  location: string | null;
  tax_label: string | null;
  tax_rate_percent: string | null;
  notes: string | null;
  attributes: Record<string, AttributeValue>;
  owner: UserBrief | null;
  members: { user: UserBrief; role: "lead" | "member" }[];
  allowed_status_transitions: ProjectStatus[];
  version: number;
  created_at: string;
};

export type AuditEntry = {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  summary: string | null;
  changes: Record<string, { from: unknown; to: unknown }> | null;
  actor: UserBrief | null;
  created_at: string;
};

export type DashboardSummary = {
  rab: {
    draft: number;
    in_review: number;
    approved: number;
    approved_total: { currency: string; total: string; count: number }[];
  } | null;
  projects_total: number;
  projects_by_status: Record<ProjectStatus, number>;
  clients_active: number;
  open_budget: { currency: string; total: string; projects: number }[];
  documents: { issued: number; void: number; approved_rab_not_issued: number } | null;
  quotations: { draft: number; in_review: number; awaiting_response: number; accepted: number } | null;
  billing: {
    outstanding: { currency: string; total: string; count: number }[];
    overdue: { currency: string; total: string; count: number }[];
    received_this_month: { currency: string; total: string; count: number }[];
    terms_due_soon: number;
  } | null;
  workorders: {
    accepted_without_spk: number;
    spk_in_review: number;
    spk_open: number;
    bast_in_review: number;
  };
  recent_activity: AuditEntry[] | null;
};

// --------------------------------------------------------------------------- RAB

export type RabStatus = "draft" | "in_review" | "approved" | "rejected" | "archived";
export type RabAction = "submit" | "withdraw" | "approve" | "reject" | "reopen" | "archive";
export type RabItemType =
  | "material"
  | "labor"
  | "service"
  | "equipment"
  | "transport"
  | "overhead"
  | "other";
export type PriceSourceType =
  | "manual"
  | "catalog"
  | "history"
  | "vendor_quote"
  | "import"
  | "external";
export type DiscountType = "none" | "percent" | "amount";

export type ProjectRef = { id: string; number: string; name: string };

export type RabListItem = {
  id: string;
  number: string;
  title: string;
  project: ProjectRef;
  latest_version_no: number;
  latest_status: RabStatus;
  currency: string;
  grand_total: string;
  updated_at: string;
};

export type VersionSummary = {
  id: string;
  version_no: number;
  status: RabStatus;
  grand_total: string;
  currency: string;
  created_at: string;
  decided_at: string | null;
};

export type Rab = {
  id: string;
  number: string;
  title: string;
  project: ProjectRef;
  versions: VersionSummary[];
  created_at: string;
  updated_at: string;
};

export type RabTotals = {
  subtotal: string;
  discount_amount: string;
  taxable_base: string;
  tax_amount: string;
  grand_total: string;
  unpriced_items: number;
};

export type RabItem = {
  id: string;
  position: number;
  code: string | null;
  name: string;
  category: string | null;
  item_type: RabItemType;
  specification: string | null;
  quantity: string;
  unit: string;
  unit_price: string | null;
  subtotal: string | null;
  price_source_type: PriceSourceType | null;
  price_source: string | null;
  notes: string | null;
  row_version: number;
  price_observation_id: string | null;
  price_verification_status: VerificationStatus | null;
};

export type RabIssue = {
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
  item_id: string | null;
};

export type ApprovalAction =
  | "submitted"
  | "withdrawn"
  | "approved"
  | "rejected"
  | "reopened"
  | "archived"
  | "superseded";

export type ApprovalEntry = {
  action: ApprovalAction;
  from_status: string;
  to_status: string;
  actor: UserBrief | null;
  note: string | null;
  created_at: string;
};

export type RabVersion = VersionSummary & {
  based_on_version_id: string | null;
  tax_label: string | null;
  tax_rate_percent: string | null;
  discount_type: DiscountType;
  discount_value: string;
  notes: string | null;
  assumptions: string | null;
  totals: RabTotals;
  items: RabItem[];
  issues: RabIssue[];
  approvals: ApprovalEntry[];
  submitted_by: UserBrief | null;
  submitted_at: string | null;
  decided_by: UserBrief | null;
  lock_version: number;
  editable: boolean;
  allowed_actions: RabAction[];
  can_create_version: boolean;
};

export type CompareLine = {
  kind: "added" | "removed" | "changed" | "unchanged";
  code: string | null;
  name: string;
  unit: string;
  before_quantity: string | null;
  after_quantity: string | null;
  before_unit_price: string | null;
  after_unit_price: string | null;
  before_subtotal: string | null;
  after_subtotal: string | null;
  subtotal_delta: string;
  changed_fields: string[];
};

export type RabComparison = {
  from_version_no: number;
  to_version_no: number;
  currency: string;
  lines: CompareLine[];
  before_totals: RabTotals;
  after_totals: RabTotals;
  grand_total_delta: string;
};

export type PendingApproval = {
  rab_id: string;
  number: string;
  title: string;
  project: ProjectRef;
  version_no: number;
  currency: string;
  grand_total: string;
  submitted_by: UserBrief | null;
  submitted_at: string | null;
};

// --------------------------------------------------------------------------- price catalog

export type VerificationStatus = "unverified" | "verified" | "rejected";
export type ObservationSource = "manual" | "vendor_quote" | "import" | "external";
export type MatchLevel = "high" | "medium" | "low";

export type SupplierBrief = { id: string; name: string };

export type Supplier = SupplierBrief & {
  contact_person: string | null;
  phone: string | null;
  email: string | null;
  city: string | null;
  address: string | null;
  notes: string | null;
  is_active: boolean;
  version: number;
};

export type PriceObservation = {
  id: string;
  catalog_item_id: string;
  price: string;
  currency: string;
  unit: string;
  supplier: SupplierBrief | null;
  source_type: ObservationSource;
  source_reference: string | null;
  source_url: string | null;
  observed_specification: string | null;
  match_level: MatchLevel | null;
  observed_at: string;
  valid_from: string | null;
  valid_until: string | null;
  location: string | null;
  verification_status: VerificationStatus;
  verified_by: UserBrief | null;
  verified_at: string | null;
  verification_note: string | null;
  notes: string | null;
  import_job_id: string | null;
  created_at: string;
};

export type PriceSummary = {
  latest_verified: PriceObservation | null;
  latest_any: PriceObservation | null;
  observation_count: number;
};

export type CatalogItem = {
  id: string;
  code: string | null;
  name: string;
  category: string | null;
  brand: string | null;
  specification: string | null;
  unit: string;
  item_type: RabItemType;
  is_active: boolean;
  notes: string | null;
  version: number;
  updated_at: string;
};

export type CatalogListItem = CatalogItem & { prices: PriceSummary };
export type CatalogItemDetail = CatalogItem & {
  prices: PriceSummary;
  observations: PriceObservation[];
};

export type PriceCandidate = {
  kind: "catalog" | "history";
  score: number;
  level: MatchLevel;
  unit_compatible: boolean;
  reasons: string[];
  warnings: string[];
  name: string;
  unit: string;
  brand: string | null;
  specification: string | null;
  price: string;
  currency: string;
  observed_at: string | null;
  verified: boolean;
  catalog_item_id: string | null;
  observation_id: string | null;
  supplier: string | null;
  source_reference: string | null;
  reference: string | null;
};

export type ExternalSearchStatus = { configured: boolean; provider: string | null; message: string };

export type ImportRow = {
  row: number;
  valid: boolean;
  errors: string[];
  data: Record<string, string | null>;
  action: "create_item" | "add_price" | "add_item" | null;
};

export type ImportJob = {
  id: string;
  status: "previewed" | "committed" | "discarded";
  filename: string;
  row_count: number;
  valid_count: number;
  error_count: number;
  warnings: string[];
  rows: ImportRow[];
  /** Counts per kind of record created, e.g. items_created, prices_created. */
  result: Record<string, number> | null;
  created_at: string;
  committed_at: string | null;
};

// --------------------------------------------------------------------------- documents

export type DocumentType = "rab" | "quotation" | "invoice" | "spk" | "bast";
export type DocumentStatus = "issued" | "void";
export type FileFormat = "pdf" | "xlsx";

export type DocumentFile = {
  format: FileFormat;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
};

export type IssuedDocument = {
  id: string;
  doc_type: DocumentType;
  status: DocumentStatus;
  number: string;
  title: string;
  project_id: string | null;
  rab_version_id: string | null;
  quotation_id: string | null;
  invoice_id: string | null;
  spk_id: string | null;
  bast_id: string | null;
  currency: string;
  total_amount: string;
  snapshot_sha256: string;
  schema_version: number;
  issued_at: string;
  issued_by: UserBrief | null;
  voided_at: string | null;
  voided_by: UserBrief | null;
  void_reason: string | null;
  files: DocumentFile[];
};

/** The frozen data of an issued RAB document (fields the UI reads; see documents/snapshot.py). */
export type RabSnapshot = {
  schema_version: number;
  document: { number: string | null; issued_at: string | null; issued_by: string | null };
  company: { name: string; legal_name: string | null };
  client: { name: string } | null;
  project: { number: string; name: string };
  rab: {
    id: string;
    number: string;
    title: string;
    version_no: number;
    status_label: string;
    currency: string;
    approved_by: string | null;
    approved_at: string | null;
  };
  items: { no: number }[];
  totals: {
    subtotal: string;
    discount_amount: string;
    tax_label: string | null;
    tax_rate_percent: string | null;
    tax_amount: string;
    grand_total: string;
    amount_in_words: string | null;
  };
};

/** Fields every document snapshot has (quotation, invoice, SPK and BAST add their own sections). */
export type CommonSnapshot = {
  schema_version: number;
  document: { number: string | null; issued_at: string | null; issued_by: string | null };
  company: { name: string; legal_name: string | null };
  client: { name: string } | null;
  project: { number: string; name: string };
};

export type IssuedDocumentDetail = IssuedDocument & { snapshot: RabSnapshot | CommonSnapshot };

export type DocumentSettings = {
  tagline: string | null;
  accent_color: string;
  footer_text: string | null;
  rab_terms: string | null;
  show_item_codes: boolean;
  show_price_sources: boolean;
  show_amount_in_words: boolean;
  payment_bank_name: string | null;
  payment_account_number: string | null;
  payment_account_holder: string | null;
  spk_terms: string | null;
  bast_terms: string | null;
  version: number;
  updated_at: string | null;
};

/** The organization's uploaded letterhead (kop surat); the PNG is a separate download. */
export type Letterhead = {
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  width_px: number;
  height_px: number;
  uploaded_at: string;
  uploaded_by: UserBrief | null;
};

// --------------------------------------------------------------------------- billing

export type DocStatus = "draft" | "in_review" | "approved" | "rejected" | "issued" | "void";
export type DocAction = "submit" | "withdraw" | "approve" | "reject" | "reopen";
export type ClientResponse = "accepted" | "declined";
export type TermBasis = "percent" | "amount";
export type InvoiceKind = "term" | "manual";
export type PaymentMethod = "transfer" | "cash" | "cheque" | "giro" | "other";
export type PaymentStatus = "recorded" | "void";
export type PaymentState = "unpaid" | "partial" | "paid";

export type Brief = { id: string; number: string | null; name: string };
export type RefBrief = { id: string; number: string | null };

type WorkflowFields = {
  submitted_by: UserBrief | null;
  submitted_at: string | null;
  decided_by: UserBrief | null;
  decided_at: string | null;
  voided_at: string | null;
  void_reason: string | null;
  version: number;
  approvals: ApprovalEntry[];
  allowed_actions: DocAction[];
  editable: boolean;
  can_issue: boolean;
  can_void: boolean;
  can_delete: boolean;
};

export type PaymentTerm = {
  id: string;
  position: number;
  name: string;
  basis: TermBasis;
  percent: string | null;
  amount: string;
  tax_amount: string;
  total_amount: string;
  due_date: string | null;
  description: string | null;
  invoice: { id: string; number: string | null; status: DocStatus; payment_state: PaymentState | null } | null;
};

export type QuotationListItem = {
  id: string;
  number: string;
  status: DocStatus;
  subject: string;
  project: Brief;
  client: Brief | null;
  rab: RefBrief;
  rab_version_no: number;
  currency: string;
  grand_total: string;
  valid_until: string | null;
  expired: boolean;
  client_response: ClientResponse | null;
  created_at: string;
  updated_at: string;
};

export type Quotation = QuotationListItem &
  WorkflowFields & {
    introduction: string | null;
    scope: string | null;
    terms: string | null;
    notes: string | null;
    subtotal: string;
    discount_amount: string;
    taxable_base: string;
    tax_label: string | null;
    tax_rate_percent: string | null;
    tax_amount: string;
    payment_terms: PaymentTerm[];
    responded_at: string | null;
    response_note: string | null;
    can_respond: boolean;
    can_invoice: boolean;
    spk: { id: string; number: string | null; status: DocStatus } | null;
    can_create_spk: boolean;
  };

export type InvoiceLine = {
  id: string;
  position: number;
  description: string;
  quantity: string;
  unit: string;
  unit_price: string;
  amount: string;
};

export type Allocation = {
  payment_id: string;
  invoice_id: string;
  invoice_number: string | null;
  payment_date: string;
  method: PaymentMethod;
  reference: string | null;
  amount: string;
  payment_status: PaymentStatus;
};

export type InvoiceListItem = {
  id: string;
  number: string | null;
  kind: InvoiceKind;
  status: DocStatus;
  title: string;
  project: Brief;
  client: Brief;
  quotation: RefBrief | null;
  issue_date: string | null;
  due_date: string | null;
  currency: string;
  grand_total: string;
  amount_paid: string;
  outstanding: string;
  payment_state: PaymentState | null;
  overdue: boolean;
  created_at: string;
};

export type Invoice = InvoiceListItem &
  WorkflowFields & {
    payment_term: { id: string; name: string; percent: string | null } | null;
    tax_label: string | null;
    tax_rate_percent: string | null;
    subtotal: string;
    tax_amount: string;
    notes: string | null;
    items: InvoiceLine[];
    allocations: Allocation[];
    lines_editable: boolean;
    can_record_payment: boolean;
  };

export type Payment = {
  id: string;
  client: Brief;
  payment_date: string;
  amount: string;
  currency: string;
  method: PaymentMethod;
  reference: string | null;
  notes: string | null;
  status: PaymentStatus;
  allocated: string;
  unallocated: string;
  allocations: Allocation[];
  recorded_by: UserBrief | null;
  created_at: string;
  voided_at: string | null;
  voided_by: UserBrief | null;
  void_reason: string | null;
};

// --------------------------------------------------------------------------- SPK & BAST

export type BastKind = "partial" | "final";

export type SpkListItem = {
  id: string;
  number: string | null;
  status: DocStatus;
  title: string;
  project: Brief;
  client: Brief;
  quotation: RefBrief;
  currency: string;
  contract_value: string;
  issue_date: string | null;
  start_date: string | null;
  end_date: string | null;
  bast_count: number;
  created_at: string;
  updated_at: string;
};

export type Spk = SpkListItem &
  WorkflowFields & {
    location: string | null;
    scope: string | null;
    terms: string | null;
    notes: string | null;
    client_signatory_name: string | null;
    client_signatory_title: string | null;
    company_signatory_name: string | null;
    company_signatory_title: string | null;
    taxable_base: string;
    tax_label: string | null;
    tax_rate_percent: string | null;
    tax_amount: string;
    payment_terms: PaymentTerm[];
    rab: RefBrief;
    rab_version_no: number;
    can_create_bast: boolean;
  };

export type ContractItemProgress = {
  rab_item_id: string;
  no: number;
  code: string | null;
  name: string;
  category: string | null;
  unit: string;
  contract_quantity: string;
  delivered_quantity: string;
  pending_quantity: string;
  remaining_quantity: string;
};

export type SpkProgress = {
  spk_id: string;
  items: ContractItemProgress[];
  final_bast: RefBrief | null;
};

export type BastLine = {
  id: string;
  position: number;
  rab_item_id: string | null;
  description: string;
  quantity: string;
  unit: string;
  condition: string | null;
};

export type BastListItem = {
  id: string;
  number: string | null;
  status: DocStatus;
  kind: BastKind;
  title: string;
  spk: RefBrief;
  project: Brief;
  client: Brief;
  handover_date: string | null;
  item_count: number;
  created_at: string;
  updated_at: string;
};

export type Bast = BastListItem &
  WorkflowFields & {
    location: string | null;
    delivered_by_name: string | null;
    delivered_by_title: string | null;
    received_by_name: string | null;
    received_by_title: string | null;
    terms: string | null;
    notes: string | null;
    items: BastLine[];
  };

// --------------------------------------------------------------------------- AI assistant

export type AiState = "disabled" | "ready" | "unavailable" | "unsafe";
export type AiStatus = {
  enabled: boolean;
  state: AiState;
  message: string;
  model: string | null;
  toolsets: string[];
  ocr: { available: boolean; message: string };
  upload_max_mb: number;
  accepted_files: string;
};
export type AiRunKind = "rab_draft" | "extract_items" | "extract_document";
export type AiRunStatus = "queued" | "running" | "succeeded" | "failed" | "applied" | "discarded";
export type NumberFormat = "id" | "en";

export type AiDraftItem = {
  name: string;
  category: string | null;
  item_type: RabItemType;
  specification: string | null;
  quantity: string | null;
  unit: string | null;
  notes: string | null;
  warnings: string[];
};

export type AiExtractItem = {
  name: string;
  specification: string | null;
  quantity: string | null;
  unit: string | null;
  unit_price: string | null;
  total: string | null;
  source_line: number | null;
  /** Uploaded files: where a person finds the row ("Halaman 2", line 5 of that page). */
  source_page?: string | null;
  source_page_line?: number | null;
  source_excerpt: string | null;
  unknown_fields: string[];
  warnings: string[];
};

export type AiRunListItem = {
  id: string;
  kind: AiRunKind;
  status: AiRunStatus;
  created_by: UserBrief;
  created_at: string;
  finished_at: string | null;
  item_count: number;
  applied_count: number | null;
  error_message: string | null;
};

export type AiDocumentSummary = { pages: number; lines: number; chunks: number; ocr_pages: number; lines_left_out: number };

export type AiRun = AiRunListItem & {
  rab_version_id: string | null;
  source_document_id: string | null;
  input: {
    description?: string;
    text?: string;
    source_label?: string | null;
    source_document_id?: string;
    number_format: NumberFormat;
  };
  context: {
    project?: { number: string; name: string; project_type_label: string; location: string | null; currency: string };
    rab: { number: string; title: string; version_no: number; item_count: number; items: { no: number; name: string }[] };
    document?: { filename: string; kind: SourceKind; size_bytes: number };
  };
  result:
    | { items: AiDraftItem[]; assumptions: string[]; questions: string[]; warnings: string[] }
    | { items: AiExtractItem[]; notes: string[]; warnings: string[]; document?: AiDocumentSummary }
    | null;
  error_code: string | null;
  model: string | null;
  attempts: number;
  duration_ms: number | null;
  started_at: string | null;
  applied_at: string | null;
  can_apply: boolean;
  can_discard: boolean;
};

// --------------------------------------------------------------------------- source documents (Phase 9)

export type SourceKind = "pdf" | "xlsx" | "csv" | "image";

export type SourceDocument = {
  id: string;
  project_id: string;
  filename: string;
  content_type: string;
  kind: SourceKind;
  size_bytes: number;
  sha256: string;
  uploaded_by: UserBrief;
  created_at: string;
};

export type SourceUpload = SourceDocument & { duplicate: boolean };

export type SourceText = {
  read: boolean;
  pages: { no: number; label: string; method: "teks" | "tabel" | "ocr" | "kosong"; lines: string[] }[];
  warnings: string[];
};

// --------------------------------------------------------------------------- project chat (Phase 9)

export type ChatSource = {
  id: string;
  kind: string;
  label: string;
  ref: { type: string; id: string } | null;
  data: Record<string, unknown>;
  /** False: not cited by the AI, but where a number in its answer actually came from. */
  cited?: boolean;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: ChatSource[];
  warnings: string[];
  assumptions: string[];
  questions: string[];
  created_at: string;
};

export type ChatRun = {
  id: string;
  status: AiRunStatus;
  error_code: string | null;
  error_message: string | null;
  model: string | null;
  duration_ms: number | null;
  created_at: string;
  finished_at: string | null;
};

export type ConversationListItem = {
  id: string;
  project_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
};

export type Conversation = Omit<ConversationListItem, "message_count"> & {
  messages: ChatMessage[];
  latest_run: ChatRun | null;
  unavailable: string[];
};
