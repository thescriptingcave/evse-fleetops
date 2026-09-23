import React, { useEffect, useState } from "react";
import { Pressable, SafeAreaView, StatusBar, StyleSheet, Text, View } from "react-native";
import { StationsScreen, SyncScreen, WorkOrdersScreen } from "./screens/Screens";
import { openFleetStore } from "./store";
import type { FleetStore } from "./store";
import type { Station, SyncStatus, WorkOrder } from "./types";

type Tab = "stations" | "workorders" | "sync";

const TABS: { id: Tab; label: string }[] = [
  { id: "stations", label: "Stations" },
  { id: "workorders", label: "Work Orders" },
  { id: "sync", label: "Sync" },
];

export default function App() {
  const [store, setStore] = useState<FleetStore | null>(null);
  const [stations, setStations] = useState<Station[]>([]);
  const [orders, setOrders] = useState<WorkOrder[]>([]);
  const [sync, setSync] = useState<SyncStatus>({
    mode: "mock",
    replicator: "stopped",
    progress: 0,
    pending: 0,
    lastSync: null,
  });
  const [tab, setTab] = useState<Tab>("stations");
  const [error, setError] = useState<string | null>(null);

  const refresh = async (st: FleetStore | null = store) => {
    if (!st) return;
    try {
      const [s, o, sy] = await Promise.all([st.listStations(), st.listWorkOrders(), st.syncStatus()]);
      setStations(s);
      setOrders(o);
      setSync(sy);
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => {
    openFleetStore()
      .then((st) => {
        setStore(st);
        void refresh(st); // `store` state isn't updated until the next render
      })
      .catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const t = setInterval(() => store && refresh(), 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store]);

  useEffect(() => {
    if (error) {
      const t = setTimeout(() => setError(null), 6000);
      return () => clearTimeout(t);
    }
  }, [error]);

  const addNote = async (id: string, author: string, text: string) => {
    if (!store || !text) return;
    await store.addNote(id, author, text);
    void refresh();
  };

  return (
    <SafeAreaView style={styles.root}>
      <StatusBar barStyle="light-content" />
      <View style={styles.header}>
        <Text style={styles.title}>⚡ EVSE Technician</Text>
        <Text style={styles.mode}>{store?.mode ?? "loading…"}</Text>
      </View>
      <View style={styles.controls}>
        {TABS.map((t) => (
          <Pressable
            key={t.id}
            onPress={() => setTab(t.id)}
            style={[styles.tab, tab === t.id && styles.tabActive]}
          >
            <Text style={[styles.tabText, tab === t.id && styles.tabTextActive]}>{t.label}</Text>
          </Pressable>
        ))}
      </View>

      {error ? (
        <View style={styles.errorBar}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : null}

      <View style={styles.body}>
        {tab === "stations" && <StationsScreen stations={stations} />}
        {tab === "workorders" && <WorkOrdersScreen orders={orders} onAddNote={addNote} />}
        {tab === "sync" && <SyncScreen status={sync} />}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#020617" },
  header: {
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 8,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  title: { color: "#f1f5f9", fontSize: 18, fontWeight: "700" },
  mode: {
    color: "#34d399",
    fontSize: 11,
    fontWeight: "600",
    textTransform: "uppercase",
  },
  controls: {
    flexDirection: "row",
    gap: 8,
    paddingHorizontal: 16,
    paddingBottom: 12,
  },
  tab: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 8,
    backgroundColor: "#0f172a",
  },
  tabActive: { backgroundColor: "#1e293b" },
  tabText: { color: "#64748b", fontSize: 13 },
  tabTextActive: { color: "#f8fafc", fontWeight: "600" },
  errorBar: {
    marginHorizontal: 16,
    marginBottom: 8,
    backgroundColor: "#450a0a",
    borderRadius: 8,
    padding: 10,
  },
  errorText: { color: "#fecaca", fontSize: 12 },
  body: { flex: 1 },
});