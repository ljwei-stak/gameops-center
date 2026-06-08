CREATE TABLE IF NOT EXISTS regions (
  id VARCHAR(64) PRIMARY KEY,
  name VARCHAR(128) NOT NULL,
  city VARCHAR(128) NOT NULL,
  owner VARCHAR(128) NOT NULL,
  traffic_weight INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS workloads (
  id VARCHAR(128) PRIMARY KEY,
  name VARCHAR(128) NOT NULL,
  region VARCHAR(64) NOT NULL,
  game_mode VARCHAR(128) NOT NULL,
  namespace VARCHAR(128) NOT NULL,
  deployment VARCHAR(128) NOT NULL,
  service VARCHAR(128) NOT NULL,
  container VARCHAR(128) NOT NULL,
  image VARCHAR(512) NOT NULL,
  version VARCHAR(64) NOT NULL,
  replicas INT NOT NULL,
  desired_replicas INT NOT NULL,
  min_replicas INT NOT NULL,
  max_replicas INT NOT NULL,
  players INT NOT NULL,
  capacity_per_pod INT NOT NULL,
  cpu DOUBLE NOT NULL,
  memory DOUBLE NOT NULL,
  latency_p95 DOUBLE NOT NULL,
  packet_loss DOUBLE NOT NULL,
  rps INT NOT NULL,
  status VARCHAR(32) NOT NULL,
  metrics_source VARCHAR(64) NOT NULL DEFAULT 'seed',
  updated_at VARCHAR(40) NOT NULL,
  CONSTRAINT fk_workloads_region FOREIGN KEY (region) REFERENCES regions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS logs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  time VARCHAR(40) NOT NULL,
  level VARCHAR(16) NOT NULL,
  source VARCHAR(128) NOT NULL,
  region VARCHAR(64),
  workload_id VARCHAR(128),
  actor VARCHAR(128),
  message TEXT NOT NULL,
  INDEX idx_logs_level_id (level, id),
  INDEX idx_logs_time (time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS alerts (
  id VARCHAR(191) PRIMARY KEY,
  active TINYINT(1) NOT NULL DEFAULT 1,
  severity VARCHAR(16) NOT NULL,
  title VARCHAR(191) NOT NULL,
  region VARCHAR(64),
  workload_id VARCHAR(128),
  workload_name VARCHAR(128),
  metric VARCHAR(64) NOT NULL,
  value_text VARCHAR(128) NOT NULL,
  threshold_text VARCHAR(128) NOT NULL,
  runbook TEXT NOT NULL,
  first_seen VARCHAR(40) NOT NULL,
  last_seen VARCHAR(40) NOT NULL,
  INDEX idx_alerts_active_severity (active, severity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS deployments (
  id VARCHAR(64) PRIMARY KEY,
  version VARCHAR(64) NOT NULL,
  image VARCHAR(512) NOT NULL,
  region VARCHAR(64) NOT NULL,
  strategy VARCHAR(32) NOT NULL,
  status VARCHAR(32) NOT NULL,
  operator VARCHAR(128) NOT NULL,
  target_count INT NOT NULL,
  workloads_json JSON NOT NULL,
  command_results_json JSON NOT NULL,
  started_at VARCHAR(40) NOT NULL,
  finished_at VARCHAR(40) NOT NULL,
  INDEX idx_deployments_started_at (started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS deployment_approvals (
  id VARCHAR(64) PRIMARY KEY,
  status VARCHAR(32) NOT NULL,
  region VARCHAR(64) NOT NULL,
  version VARCHAR(64) NOT NULL,
  strategy VARCHAR(32) NOT NULL,
  image VARCHAR(512),
  requested_by VARCHAR(128) NOT NULL,
  approved_by VARCHAR(128),
  requested_at VARCHAR(40) NOT NULL,
  approved_at VARCHAR(40),
  executed_at VARCHAR(40),
  change_window VARCHAR(128),
  reason TEXT,
  rejection_reason TEXT,
  deployment_id VARCHAR(64),
  payload_json JSON NOT NULL,
  INDEX idx_deployment_approvals_status (status),
  INDEX idx_deployment_approvals_requested_at (requested_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rollback_records (
  id VARCHAR(64) PRIMARY KEY,
  deployment_id VARCHAR(64) NOT NULL,
  rollback_deployment_id VARCHAR(64),
  operator VARCHAR(128) NOT NULL,
  reason TEXT,
  from_version VARCHAR(64),
  to_version VARCHAR(64),
  workloads_json JSON NOT NULL,
  command_results_json JSON NOT NULL,
  created_at VARCHAR(40) NOT NULL,
  INDEX idx_rollback_deployment_id (deployment_id),
  INDEX idx_rollback_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS metric_history (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  time VARCHAR(40) NOT NULL,
  online_players INT NOT NULL,
  avg_latency DOUBLE NOT NULL,
  active_alerts INT NOT NULL,
  host_cpu DOUBLE NOT NULL,
  host_memory DOUBLE NOT NULL,
  host_disk DOUBLE NOT NULL,
  INDEX idx_metric_history_id (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS users (
  username VARCHAR(128) PRIMARY KEY,
  display_name VARCHAR(128) NOT NULL,
  role VARCHAR(64) NOT NULL,
  password_hash VARCHAR(128) NOT NULL,
  salt VARCHAR(64) NOT NULL,
  created_at VARCHAR(40) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sessions (
  token VARCHAR(191) PRIMARY KEY,
  username VARCHAR(128) NOT NULL,
  expires_at VARCHAR(40) NOT NULL,
  created_at VARCHAR(40) NOT NULL,
  CONSTRAINT fk_sessions_user FOREIGN KEY (username) REFERENCES users(username),
  INDEX idx_sessions_expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
