function out = tc_prob_jma_windfield_from_txt()
% TC_PROB_JMA_WINDFIELD_FROM_TXT
% 目的：用 JMA Best Track (bst_all.txt) 的 30kt/50kt 风圈半径，评估特定位置(含半径R区域)的风圈影响概率
%
% 输入：本地 bst_all.txt（你已解压得到）
% 风圈字段（适配你贴的格式）：
%   ... wind  [DLLLL] [SSSS]   [DLLLL] [SSSS]
%            50kt           30kt
% 其中 DLLLL 为5位整数：D=方向编码(0-9)，LLLL=最长半径(nm)
% SSSS 为最短半径(nm)
%
% 影响判定（工程稳健近似）：
%   生成目标区域（中心点 + 圆周若干点）；任一点落入台风风圈椭圆 -> 该时刻影响
% 台风命中：
%   任一时刻影响 -> 该台风命中
%
% 输出：
%   out.summary / out.perStorm / out.hitsByYear
%
% 备注：JMA 阈值是 30kt/50kt（不是 34kt）

%% ================== 0) 用户参数 ==================
bstTxtPath = fullfile(pwd, "bst_all.txt"); % bst_all.txt 路径

lat0 = 20.9339;      % 目标纬度 (deg)
lon0 = 112.202;     % 目标经度 (deg, East positive)
R_km = 200;         % 目标区域半径 (km); 若只看"点是否被覆盖"，设0

yearRange = [1976, 2025];  % 统计年份范围
months = 1:12;             % 统计月份；例如 7:10

windThreshold = 50;        % 30 或 50：选择风圈阈值
nBoundary = 144;            % 圆周采样点数量（36~144；越大越稳但更慢）
outDir = fullfile(pwd, "out_tc_prob"); % 输出目录

%% =============================================================

assert(exist(bstTxtPath,'file')==2, "找不到 bst_all.txt：%s", bstTxtPath);
if ~exist(outDir,'dir'); mkdir(outDir); end
assert(ismember(windThreshold, [30,50]), "windThreshold 只能是 30 或 50");

%% Step 1) 解析 bst_all.txt（含风圈）
T = read_jma_bst_all_with_radii(bstTxtPath);

% Step 2) 时间转换：yymmddhh(数值) -> 固定8位字符串 -> datetime(UTC)
tstr = arrayfun(@(x) sprintf('%08d', x), T.yymmddhh, 'UniformOutput', false);
tstr = string(tstr);
t = datetime(tstr, 'InputFormat', 'yyMMddHH', 'TimeZone', 'UTC');

% 显式世纪映射：51-99 -> 1951-1999, 00-50 -> 2000-2050（覆盖1951-2025）
yy = double(extractBetween(tstr, 1, 2));
yy = str2double(yy);
t.Year(yy >= 51) = 1900 + yy(yy >= 51);
t.Year(yy <= 50) = 2000 + yy(yy <= 50);

T.time = t;

%% Step 3) 筛选窗口
T = T(year(T.time) >= yearRange(1) & year(T.time) <= yearRange(2), :);
T = T(ismember(month(T.time), months), :);

stormIDs = unique(T.storm_id);
nStorm = numel(stormIDs);
if nStorm == 0
    error("筛选后没有任何台风样本。请检查 yearRange/months 设置。");
end

%% Step 4) 生成目标区域采样点（中心+圆周）
[latS, lonS] = make_circle_samples(lat0, lon0, R_km, nBoundary);

%% Step 5) 逐台风判定命中
hit = false(nStorm,1);
minCenterDist_km = nan(nStorm,1);
firstHitTime = repmat(datetime(NaT,'TimeZone','UTC'), nStorm, 1);

for i = 1:nStorm
    sid = stormIDs(i);
    Ts = T(T.storm_id == sid, :);
    Ts = sortrows(Ts, 'time');

    % 中心最小距离（参考指标）
    minCenterDist_km(i) = min(haversine_km(Ts.lat, Ts.lon, lat0, lon0));

    isHit = false;
    hitTime = datetime(NaT,'TimeZone','UTC');

    for k = 1:height(Ts)
        if windThreshold == 50
            dirCode  = Ts.dir50(k);
            rLong_nm = Ts.r50_long_nm(k);
            rShort_nm= Ts.r50_short_nm(k);
        else
            dirCode  = Ts.dir30(k);
            rLong_nm = Ts.r30_long_nm(k);
            rShort_nm= Ts.r30_short_nm(k);
        end

        if ~(isfinite(rLong_nm) && rLong_nm > 0)
            continue;
        end

        % nm -> km
        a_km = rLong_nm * 1.852;  % 半长轴
        b_km = rShort_nm * 1.852; % 半短轴

        % 方向编码 -> 长轴指向方位角
        phi_deg = dircode_to_bearing_deg(dirCode);
        if isnan(phi_deg); phi_deg = 0; end

        % 对称圆
        if round(dirCode) == 9
            b_km = a_km;
        end

        % 判定：区域采样点任一点落入椭圆
        if any(points_inside_wind_ellipse(latS, lonS, Ts.lat(k), Ts.lon(k), a_km, b_km, phi_deg))
            isHit = true;
            hitTime = Ts.time(k);
            break;
        end
    end

    hit(i) = isHit;
    firstHitTime(i) = hitTime;
end

%% Step 6) 统计概率
nHit = sum(hit);
p_storm = nHit / nStorm;

% 年发生概率（Poisson）
hitStormIDs = stormIDs(hit);
hitYears = zeros(numel(hitStormIDs),1);
for j = 1:numel(hitStormIDs)
    sid = hitStormIDs(j);
    Ts = T(T.storm_id == sid, :);
    hitYears(j) = year(min(Ts.time));
end

yrs = yearRange(1):yearRange(2);
hitsByYear = arrayfun(@(yy) sum(hitYears==yy), yrs);
lambda = sum(hitsByYear) / numel(yrs);
p_year = 1 - exp(-lambda);

%% Step 7) 输出与保存
fprintf("=====================================\n");
fprintf("JMA wind-radii impact probability (bst_all.txt)\n");
fprintf("Target center (%.3f, %.3f), region R = %.1f km\n", lat0, lon0, R_km);
fprintf("Window: %d-%d, months=%s\n", yearRange(1), yearRange(2), mat2str(months));
fprintf("Wind threshold: %d kt (JMA)\n", windThreshold);
fprintf("N storms = %d, N hit = %d\n", nStorm, nHit);
fprintf("p_storm = %.4f (%.2f%%)\n", p_storm, 100*p_storm);
fprintf("lambda = %.3f /year, p_year = %.4f (%.2f%%)\n", lambda, p_year, 100*p_year);
fprintf("=====================================\n");

out.summary = table(lat0, lon0, R_km, yearRange(1), yearRange(2), string(mat2str(months)), ...
    windThreshold, nStorm, nHit, p_storm, lambda, p_year, ...
    'VariableNames', {'lat0','lon0','R_km','year_start','year_end','months',...
    'windThreshold_kt','N_storm','N_hit','p_storm','lambda_per_year','p_year'});

out.perStorm = table(stormIDs, hit, minCenterDist_km, firstHitTime, ...
    'VariableNames', {'storm_id','hit','minCenterDist_km','firstHitTime_utc'});

out.hitsByYear = table(yrs(:), hitsByYear(:), 'VariableNames', {'year','hit_storms'});

writetable(out.summary,  fullfile(outDir, "summary.csv"));
writetable(out.perStorm, fullfile(outDir, "per_storm.csv"));
writetable(out.hitsByYear, fullfile(outDir, "hits_by_year.csv"));

end

%% ======================= 解析函数（适配你贴的格式） =======================
function T = read_jma_bst_all_with_radii(bstTxt)
% Header: 66666 0403   23 ...
% Data :  04051800 002 3 085 1384  996     035     00000 0000 90030 0030

fid = fopen(bstTxt, 'r');
assert(fid>0, "Cannot open: %s", bstTxt);

storm_id = [];
yymmddhh = [];
lat = []; lon = [];
pres = []; wind = [];
grade = [];

dir50 = []; r50L = []; r50S = [];
dir30 = []; r30L = []; r30S = [];

curID = NaN; remain = 0;

while ~feof(fid)
    line = fgetl(fid);
    if ~ischar(line) || strlength(string(line))==0
        continue;
    end

    if startsWith(line, "66666")
        numsH = sscanf(line, "%f");
        if numel(numsH) >= 3
            curID = numsH(2);
            remain = numsH(3);
        else
            curID = NaN; remain = 0;
        end
        continue;
    end

    if isnan(curID) || remain <= 0
        continue;
    end

    nums = sscanf(line, "%f");
    if numel(nums) >= 7
        t8 = nums(1);
        g  = nums(3);
        la = nums(4) * 0.1;
        lo = nums(5) * 0.1;
        pr = nums(6);
        wi = nums(7);

        % default no radii
        d50 = 0; L50 = 0; S50 = 0;
        d30 = 0; L30 = 0; S30 = 0;

        % optional radii (DLLLL SSSS DLLLL SSSS)
        if numel(nums) >= 11
            A50 = nums(8);  B50 = nums(9);
            A30 = nums(10); B30 = nums(11);

            [d50, L50] = split_dir_long(A50);
            S50 = round(B50);

            [d30, L30] = split_dir_long(A30);
            S30 = round(B30);
        end

        storm_id(end+1,1) = curID; %#ok<AGROW>
        yymmddhh(end+1,1) = t8;
        grade(end+1,1)    = g;
        lat(end+1,1)      = la;
        lon(end+1,1)      = lo;
        pres(end+1,1)     = pr;
        wind(end+1,1)     = wi;

        dir50(end+1,1) = d50; r50L(end+1,1) = L50; r50S(end+1,1) = S50;
        dir30(end+1,1) = d30; r30L(end+1,1) = L30; r30S(end+1,1) = S30;
    end

    remain = remain - 1;
end

fclose(fid);

T = table(storm_id, yymmddhh, grade, lat, lon, pres, wind, ...
          dir50, r50L, r50S, dir30, r30L, r30S, ...
    'VariableNames', {'storm_id','yymmddhh','grade','lat','lon','pres_hpa','wind_kt', ...
                      'dir50','r50_long_nm','r50_short_nm', ...
                      'dir30','r30_long_nm','r30_short_nm'});
end

function [dirCode, long_nm] = split_dir_long(A)
A = round(A);
dirCode = floor(A / 10000);
long_nm = mod(A, 10000);
end

%% ======================= 几何工具：区域采样 & 椭圆判定 =======================
function [latS, lonS] = make_circle_samples(lat0, lon0, R_km, nBoundary)
latS = lat0; lonS = lon0; % center
if R_km <= 0
    return;
end
az = linspace(0, 360, nBoundary+1); az(end) = [];
for i = 1:numel(az)
    [lat_i, lon_i] = destination_point(lat0, lon0, az(i), R_km);
    latS(end+1,1) = lat_i; %#ok<AGROW>
    lonS(end+1,1) = lon_i; %#ok<AGROW>
end
end

function inside = points_inside_wind_ellipse(latP, lonP, latC, lonC, a_km, b_km, phi_deg)
% d = distance from center; alpha = bearing from center to point
d = haversine_km(latP, lonP, latC, lonC);
alpha = bearing_deg(latC, lonC, latP, lonP);  % degrees, 0=N clockwise
theta = deg2rad(wrapTo360(alpha - phi_deg));

a = a_km; b = b_km;
r = (a*b) ./ sqrt( (b*cos(theta)).^2 + (a*sin(theta)).^2 );
inside = d <= r;
end

%% ======================= 球面距离/方位/终点 =======================
function dkm = haversine_km(lat1, lon1, lat2, lon2)
R = 6371.0;
lat1 = deg2rad(lat1); lon1 = deg2rad(lon1);
lat2 = deg2rad(lat2); lon2 = deg2rad(lon2);
dlat = lat2 - lat1;
dlon = lon2 - lon1;
a = sin(dlat/2).^2 + cos(lat1).*cos(lat2).*sin(dlon/2).^2;
dkm = 2*R*asin(sqrt(a));
end

function brng = bearing_deg(lat1, lon1, lat2, lon2)
lat1 = deg2rad(lat1); lon1 = deg2rad(lon1);
lat2 = deg2rad(lat2); lon2 = deg2rad(lon2);
dlon = lon2 - lon1;
x = sin(dlon).*cos(lat2);
y = cos(lat1).*sin(lat2) - sin(lat1).*cos(lat2).*cos(dlon);
brng = mod(rad2deg(atan2(x,y)) + 360, 360);
end

function phi = dircode_to_bearing_deg(code)
% JMA direction code: 1 NE,2 E,3 SE,4 S,5 SW,6 W,7 NW,8 N,9 symmetric circle
switch round(code)
    case 1, phi = 45;
    case 2, phi = 90;
    case 3, phi = 135;
    case 4, phi = 180;
    case 5, phi = 225;
    case 6, phi = 270;
    case 7, phi = 315;
    case 8, phi = 0;
    case 9, phi = 0;
    otherwise, phi = NaN;
end
end

function [lat2, lon2] = destination_point(lat1, lon1, az_deg, dist_km)
R = 6371.0;
lat1 = deg2rad(lat1); lon1 = deg2rad(lon1);
az = deg2rad(az_deg);
d = dist_km / R;

lat2 = asin( sin(lat1).*cos(d) + cos(lat1).*sin(d).*cos(az) );
lon2 = lon1 + atan2( sin(az).*sin(d).*cos(lat1), cos(d) - sin(lat1).*sin(lat2) );

lat2 = rad2deg(lat2);
lon2 = rad2deg(lon2);
lon2 = wrapTo180(lon2);
end