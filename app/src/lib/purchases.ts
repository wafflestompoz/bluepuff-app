import { Platform } from "react-native";
import Constants from "expo-constants";
import Purchases, { PurchasesPackage } from "react-native-purchases";

/** Racer and Racer Pro are bought in the app stores through RevenueCat. The server learns about it by webhook. */
const extra = (Constants.expoConfig?.extra ?? {}) as { revenuecatIosKey?: string; revenuecatAndroidKey?: string };
const key = Platform.OS === "ios" ? extra.revenuecatIosKey : Platform.OS === "android" ? extra.revenuecatAndroidKey : undefined;
let ready: Promise<void> | null = null;

export const storeAvailable = () => !!key;

export function startPurchases(userId: number) {
  if (!key) return Promise.resolve();
  ready ??= (async () => { Purchases.configure({ apiKey: key, appUserID: String(userId) }); })();
  return ready;
}

export type Offer = { id: string; title: string; price: string; period: string; pkg: PurchasesPackage };

export async function offers(userId: number): Promise<Offer[]> {
  if (!key) return [];
  await startPurchases(userId);
  const o = await Purchases.getOfferings();
  return (o.current?.availablePackages ?? []).map((p) => ({
    id: p.identifier, title: p.product.title, price: p.product.priceString,
    period: p.packageType === "ANNUAL" ? "a year" : p.packageType === "MONTHLY" ? "a month" : "", pkg: p,
  }));
}

export async function buy(o: Offer) {
  await Purchases.purchasePackage(o.pkg);
}

export async function restore(userId: number) {
  if (!key) return;
  await startPurchases(userId); await Purchases.restorePurchases();
}
