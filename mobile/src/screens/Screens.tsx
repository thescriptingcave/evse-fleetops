import React from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import type { Station, StationStatus, SyncStatus, WorkOrder, WorkOrderStatus } from "../types";

const COLORS: Record<StationStatus | WorkOrderStatus, { bg: string; fg: string }> = {
  AVAILABLE: { bg: "#14532d", fg: "#86efac" },
  CHARGING: { bg: "#0c4a6e", fg: "#7dd3fc" },
  FAULTED: { bg: "#4c0519", fg: "#fda4af" },
  MAINTENANCE: { bg: "#451a03", fg: "#fcd34d" },
  OFFLINE: { bg: "#1e293b", fg: "#cbd5e1" },
  OPEN: { bg: "#0c4a6e", fg: "#7dd3fc" },
  IN_PROGRESS: { bg: "#451a03", fg: "#fcd34d" },
  RESOLVED: { bg: "#14532d", fg: "#86efac" },
  CLOSED: { bg: "#1e293b", fg: "#cbd5e1" },
};

function Chip({ status }: { status: StationStatus | WorkOrderStatus }) {
  const c = COLORS[status] ?? COLORS.OFFLINE;
  return (
    <View style={[styles.chip, { backgroundColor: c.bg }]}>
      <Text style={[styles.chipText, { color: c.fg }]}>{status}</Text>
    </View>
  );
}

export function StationsScreen({ stations }: { stations: Station[] }) {
  return (
    <ScrollView contentContainerStyle={styles.container}>
      {stations.map((s) => (
        <View key={s.serial} style={styles.card}>
          <View style={styles.cardTop}>
            <Text style={styles.name}>{s.name}</Text>
            <Chip status={s.status} />
          </View>
          <Text style={styles.meta}>
            {s.serial} · {s.model}
          </Text>
          <Text style={styles.meta}>{s.site_type} · firmware {s.firmware}</Text>
        </View>
      ))}
    </ScrollView>
  );
}

export function WorkOrdersScreen({
  orders,
  onAddNote,
}: {
  orders: WorkOrder[];
  onAddNote: (id: string, author: string, text: string) => void;
}) {
  const [expanded, setExpanded] = React.useState<string | null>(null);
  const [note, setNote] = React.useState("");

  return (
    <ScrollView contentContainerStyle={styles.container}>
      {orders.map((wo) => (
        <View key={wo.id} style={styles.card}>
          <Pressable onPress={() => setExpanded(expanded === wo.id ? null : wo.id)}>
            <View style={styles.cardTop}>
              <Text style={styles.name}>{wo.title}</Text>
              <Chip status={wo.status} />
            </View>
            <Text style={styles.meta}>
              {wo.station_id} · {wo.priority} · {wo.assignee ?? "unassigned"}
            </Text>
          </Pressable>

          {expanded === wo.id && (
            <View style={styles.expanded}>
              {wo.notes.map((n, i) => (
                <View key={i} style={styles.note}>
                  <Text style={styles.noteAuthor}>
                    {n.author} · {new Date(n.ts).toLocaleString()}
                  </Text>
                  <Text style={styles.noteText}>{n.text}</Text>
                </View>
              ))}
              <TextInputRow
                value={note}
                onChange={setNote}
                onSubmit={() => {
                  onAddNote(wo.id, "tech_garcia", note.trim());
                  setNote("");
                }}
                placeholder="Add offline note… (queued until sync)"
              />
            </View>
          )}
        </View>
      ))}
    </ScrollView>
  );
}

function TextInputRow({
  value,
  onChange,
  onSubmit,
  placeholder,
}: {
  value: string;
  onChange: (t: string) => void;
  onSubmit: () => void;
  placeholder: string;
}) {
  return (
    <View style={styles.inputRow}>
      <TextInput
        value={value}
        onChangeText={onChange}
        onSubmitEditing={onSubmit}
        placeholder={placeholder}
        placeholderTextColor="#475569"
        style={styles.input}
      />
      <TouchableOpacity onPress={onSubmit} style={styles.button}>
        <Text style={styles.buttonText}>Add</Text>
      </TouchableOpacity>
    </View>
  );
}

export function SyncScreen({ status }: { status: SyncStatus }) {
  return (
    <ScrollView contentContainerStyle={styles.container}>
      <View style={styles.card}>
        <Text style={styles.name}>Sync status</Text>
        <Text style={styles.meta}>Storage mode: {status.mode}</Text>
        <Text style={styles.meta}>Replicator: {status.replicator}</Text>
        <Text style={styles.meta}>
          Progress: {Math.round((status.progress ?? 0) * 100)}% · {status.pending} pending
        </Text>
        <Text style={styles.meta}>Last sync: {status.lastSync ?? "never"}</Text>
      </View>
      <View style={[styles.card, styles.infoCard]}>
        <Text style={styles.meta}>
          Offline note: Couchbase Lite keeps work orders local and syncs
          bidirectionally with Sync Gateway (delta sync, auto conflict resolution)
          — connectivity only matters at the edge.
        </Text>
      </View>
      <View style={[styles.card, styles.infoCard]}>
        <Text style={styles.meta}>
          {status.mode === "mock"
            ? "Current run uses the in-memory mock store. Set EXPO_PUBLIC_USE_COUCHBASE_LITE=1 and rebuild with a dev-client to enable the native Couchbase Lite path."
            : "Running on the native Couchbase Lite store with continuous Sync Gateway replication."}
        </Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, gap: 12 },
  card: {
    backgroundColor: "#0f172a",
    borderColor: "#1e293b",
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
  },
  infoCard: { backgroundColor: "#0c0a09", borderColor: "#292524" },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 },
  name: { color: "#f1f5f9", fontSize: 15, fontWeight: "600", flexShrink: 1 },
  meta: { color: "#94a3b8", fontSize: 12, marginTop: 4 },
  chip: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  chipText: { fontSize: 10, fontWeight: "600" },
  expanded: { marginTop: 10, gap: 8 },
  note: { borderLeftWidth: 2, borderLeftColor: "#334155", paddingLeft: 8 },
  noteAuthor: { color: "#64748b", fontSize: 11 },
  noteText: { color: "#cbd5e1", fontSize: 12, marginTop: 2 },
  inputRow: { flexDirection: "row", gap: 8, marginTop: 4 },
  input: {
    flex: 1,
    backgroundColor: "#1e293b",
    color: "#e2e8f0",
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "#334155",
  },
  button: {
    backgroundColor: "#0f766e",
    borderRadius: 8,
    paddingHorizontal: 14,
    justifyContent: "center",
  },
  buttonText: { color: "#ecfdf5", fontWeight: "600", fontSize: 13 },
});