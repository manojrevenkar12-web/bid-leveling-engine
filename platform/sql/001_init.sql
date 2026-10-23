-- System of record for bid leveling. The Python workflows publish runs here; people review
-- findings here, and their decisions carry over to later runs of the same tender.
CREATE TABLE tender (
  id              text PRIMARY KEY,
  project         text NOT NULL,
  latest_version  text NOT NULL,
  run_id          text NOT NULL,
  export          jsonb NOT NULL,          -- the whole run, for chat and export
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE boq_version (
  id         text PRIMARY KEY,             -- <tender>/<version>
  tender_id  text NOT NULL REFERENCES tender(id) ON DELETE CASCADE,
  version    text NOT NULL,
  date       text NOT NULL,
  label      text NOT NULL,
  doc_id     text NOT NULL                 -- path@sha256 prefix of the BoQ file
);

CREATE TABLE position (
  id          text PRIMARY KEY,            -- <tender>/<version>/<oz>
  version_id  text NOT NULL REFERENCES boq_version(id) ON DELETE CASCADE,
  oz          text NOT NULL,
  trade       text NOT NULL,
  short       text NOT NULL,
  long        text NOT NULL,
  qty         double precision,
  unit        text NOT NULL,
  evidence    jsonb NOT NULL
);
CREATE INDEX position_version_oz ON position(version_id, oz);

CREATE TABLE bid (
  id                text PRIMARY KEY,
  tender_id         text NOT NULL REFERENCES tender(id) ON DELETE CASCADE,
  company           text NOT NULL,
  route             text NOT NULL,         -- gaeb, xlsx, pdf_text, ocr
  priced_version    text NOT NULL,
  stated_total      double precision,
  comparable_total  double precision,
  rank              integer,
  stated_rank       integer,
  pages             integer NOT NULL,
  cost_eur          double precision NOT NULL
);
CREATE INDEX bid_tender ON bid(tender_id);

CREATE TABLE bid_line (
  id            text PRIMARY KEY,          -- <bid>/<idx>
  bid_id        text NOT NULL REFERENCES bid(id) ON DELETE CASCADE,
  idx           integer NOT NULL,
  shown_no      text NOT NULL,
  short         text NOT NULL,
  qty           double precision,
  unit          text NOT NULL,
  ep            double precision,
  gp            double precision,
  oz            text,                      -- the BoQ position it prices (entity resolution)
  match_p       double precision NOT NULL,
  needs_review  boolean NOT NULL,
  evidence      jsonb NOT NULL
);
CREATE INDEX bid_line_bid ON bid_line(bid_id);

CREATE TABLE finding (
  id            text PRIMARY KEY,          -- stable across runs: bid, type, position
  tender_id     text NOT NULL REFERENCES tender(id) ON DELETE CASCADE,
  bid_id        text NOT NULL,
  type          text NOT NULL,
  oz            text,
  severity      text NOT NULL,
  message       text NOT NULL,
  confidence    double precision NOT NULL,
  needs_review  boolean NOT NULL,
  status        text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'confirmed', 'rejected')),
  evidence      jsonb NOT NULL,
  detail        jsonb NOT NULL,
  run_id        text NOT NULL
);
CREATE INDEX finding_tender_status ON finding(tender_id, status);

-- kept when a tender is re-run (no foreign key to finding), so a rejected finding stays rejected
CREATE TABLE decision (
  id          bigserial PRIMARY KEY,
  finding_id  text NOT NULL,
  tender_id   text NOT NULL,
  verdict     text NOT NULL CHECK (verdict IN ('confirmed', 'rejected')),
  note        text,
  reviewer    text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX decision_finding ON decision(finding_id);
CREATE INDEX decision_tender ON decision(tender_id);

CREATE TABLE run (
  id              text PRIMARY KEY,
  tender_id       text NOT NULL REFERENCES tender(id) ON DELETE CASCADE,
  code_version    text NOT NULL,
  config_version  text NOT NULL,
  traces          jsonb NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chat_turn (
  id          bigserial PRIMARY KEY,
  tender_id   text NOT NULL REFERENCES tender(id) ON DELETE CASCADE,
  question    text NOT NULL,
  answer      jsonb NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
