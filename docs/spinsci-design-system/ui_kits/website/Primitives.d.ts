export interface SpinIconProps { name: string; size?: number; color?: string; strokeWidth?: number; }
export function SpinIcon(props: SpinIconProps): any;
export interface EyebrowProps { children?: any; onDark?: boolean; }
export function Eyebrow(props: EyebrowProps): any;
export interface IconBoxProps { name: string; tint?: "mint" | "violet" | "onDark"; size?: number; icon?: number; }
export function IconBox(props: IconBoxProps): any;
export interface ButtonProps { children?: any; variant?: "primary" | "secondary" | "ghost" | "onDark"; icon?: string | null; onClick?: () => void; size?: "md" | "lg"; }
export function Button(props: ButtonProps): any;
export interface PrimitivesProps {}
export const Primitives: { SpinIcon: any; Eyebrow: any; IconBox: any; Button: any };
